"""Process completed prints and deduct filament from mapped spools."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from bambu.filament_rfid import lookup_filament, pick_active_spool
from bambu.task_guard import (
    is_before_baseline,
    is_bambu_task_ignored,
    should_deduct_auto_import,
)
from db import connect, deduct_spool_weight, set_sync_state
from routes.ams import update_mqtt_tray_state

logger = logging.getLogger("bambu.processor")


def _color_distance(hex_a: str | None, hex_b: str | None) -> int:
    if not hex_a or not hex_b:
        return 999
    a = hex_a.lstrip("#")[:6]
    b = hex_b.lstrip("#")[:6]
    if len(a) != 6 or len(b) != 6:
        return 999
    try:
        ar, ag, ab = int(a[0:2], 16), int(a[2:4], 16), int(a[4:6], 16)
        br, bg, bb = int(b[0:2], 16), int(b[2:4], 16), int(b[4:6], 16)
        return abs(ar - br) + abs(ag - bg) + abs(ab - bb)
    except ValueError:
        return 999


def resolve_spool_for_slot(
    conn,
    printer_id: int,
    ams_slot: int,
    material: str | None,
    color: str | None,
) -> int | None:
    mapping = conn.execute(
        """
        SELECT spool_id, mqtt_tag_uid, mqtt_tray_info_idx
        FROM ams_slot_mappings
        WHERE printer_id = ? AND slot = ?
        """,
        (printer_id, ams_slot),
    ).fetchone()
    if mapping and mapping["spool_id"]:
        return int(mapping["spool_id"])

    product = lookup_filament(
        conn,
        tag_uid=mapping["mqtt_tag_uid"] if mapping else None,
        tray_info_idx=mapping["mqtt_tray_info_idx"] if mapping else None,
    )
    if product:
        spool_id = pick_active_spool(
            conn,
            product["brand"],
            product["material"],
            product["color_name"],
        )
        if spool_id:
            return spool_id

    if material:
        candidates = conn.execute(
            """
            SELECT id, material, color_hex, brand, color_name FROM spools
            WHERE material = ? AND COALESCE(remaining_g, 0) > 0
            ORDER BY updated_at DESC
            """,
            (material.upper(),),
        ).fetchall()
        if len(candidates) == 1:
            return int(candidates[0]["id"])
        if candidates:
            best = min(candidates, key=lambda row: _color_distance(color, row["color_hex"]))
            if _color_distance(color, best["color_hex"]) <= 120:
                active = pick_active_spool(conn, best["brand"], best["material"], best["color_name"])
                if active:
                    return active
    return None


def process_print_job(
    *,
    title: str | None,
    started_at: str | None,
    ended_at: str | None,
    duration_s: int | None,
    status: str,
    source: str,
    bambu_task_id: str | None,
    gcode_file: str | None,
    completion_percent: float,
    usages: list[dict[str, Any]],
    printer_id: int = 1,
) -> dict[str, Any]:
    if bambu_task_id:
        with connect() as conn:
            if is_bambu_task_ignored(conn, bambu_task_id):
                return {"ignored": True, "bambu_task_id": bambu_task_id}
            existing = conn.execute(
                "SELECT id FROM print_jobs WHERE bambu_task_id = ?", (bambu_task_id,)
            ).fetchone()
            if existing:
                return {"id": existing["id"], "duplicate": True}
            if is_before_baseline(conn, ended_at):
                return {"ignored": True, "bambu_task_id": bambu_task_id, "reason": "before_baseline"}

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    resolved_usages: list[dict[str, Any]] = []
    needs_review = False

    with connect() as conn:
        for usage in usages:
            slot = usage.get("ams_slot") or 1
            spool_id = resolve_spool_for_slot(
                conn,
                printer_id,
                slot,
                usage.get("material"),
                usage.get("color"),
            )
            item = {
                **usage,
                "ams_slot": slot,
                "spool_id": spool_id,
                "resolved": bool(spool_id),
            }
            if not spool_id:
                needs_review = True
            resolved_usages.append(item)

        total_used = sum(float(u.get("used_g") or 0) for u in resolved_usages)
        cur = conn.execute(
            """
            INSERT INTO print_jobs (
                title, started_at, ended_at, duration_s, status, source, printer_id,
                bambu_task_id, gcode_file, needs_review, total_used_g, completion_percent
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                title or gcode_file or "Untitled",
                started_at or now,
                ended_at or now,
                duration_s,
                status,
                source,
                printer_id,
                bambu_task_id,
                gcode_file,
                1 if needs_review else 0,
                total_used,
                completion_percent,
            ),
        )
        print_id = cur.lastrowid

        scale = max(0.0, min(completion_percent, 100.0)) / 100.0
        deduct = should_deduct_auto_import(conn, ended_at=ended_at or now, source=source)
        for usage in resolved_usages:
            conn.execute(
                """
                INSERT INTO print_usages (
                    print_job_id, ams_slot, spool_id, material, color, used_g, used_m, resolved
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    print_id,
                    usage.get("ams_slot"),
                    usage.get("spool_id"),
                    usage.get("material"),
                    usage.get("color"),
                    usage.get("used_g"),
                    usage.get("used_m"),
                    1 if usage.get("spool_id") else 0,
                ),
            )
            if usage.get("spool_id") and not needs_review and deduct:
                deduct_spool_weight(conn, usage["spool_id"], float(usage.get("used_g") or 0) * scale)

    logger.info(
        "Processed print %s (%s) review=%s usages=%s",
        print_id,
        source,
        needs_review,
        len(resolved_usages),
    )
    return {"id": print_id, "needs_review": needs_review, "duplicate": False}


def store_live_state(printer_state: dict[str, Any], trays: dict[str, Any]) -> None:
    import json

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with connect() as conn:
        set_sync_state(conn, "live_printer_state", json.dumps(printer_state))
        set_sync_state(conn, "mqtt_last_print_at", now)
        # P1/P1S only includes AMS tray arrays in full pushall snapshots, not deltas.
        if trays:
            set_sync_state(conn, "live_ams_state", json.dumps(trays))
            set_sync_state(conn, "mqtt_last_ams_at", now)
            set_sync_state(conn, "mqtt_last_ams_slots", ",".join(sorted(trays.keys())))
            for slot_str, tray in trays.items():
                update_mqtt_tray_state(1, int(slot_str), tray)
