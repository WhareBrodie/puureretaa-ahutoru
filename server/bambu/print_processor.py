"""Process completed prints and deduct filament from mapped spools."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from db import connect, deduct_spool_weight, set_sync_state
from routes.ams import list_ams_slots, update_mqtt_tray_state

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
        SELECT spool_id, mqtt_tag_uid FROM ams_slot_mappings
        WHERE printer_id = ? AND slot = ?
        """,
        (printer_id, ams_slot),
    ).fetchone()
    if mapping and mapping["spool_id"]:
        return mapping["spool_id"]

    candidates = conn.execute(
        """
        SELECT id, material, color_hex FROM spools
        WHERE material = ? OR ? IS NULL
        ORDER BY updated_at DESC
        """,
        (material, material),
    ).fetchall()
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]["id"]
    best = min(candidates, key=lambda row: _color_distance(color, row["color_hex"]))
    if material and best["material"] != material:
        return None
    if _color_distance(color, best["color_hex"]) > 120:
        return None
    return best["id"]


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
            existing = conn.execute(
                "SELECT id FROM print_jobs WHERE bambu_task_id = ?", (bambu_task_id,)
            ).fetchone()
            if existing:
                return {"id": existing["id"], "duplicate": True}

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
            if usage.get("spool_id") and not needs_review:
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

    with connect() as conn:
        set_sync_state(conn, "live_printer_state", json.dumps(printer_state))
        set_sync_state(conn, "live_ams_state", json.dumps(trays))
        for slot_str, tray in trays.items():
            update_mqtt_tray_state(1, int(slot_str), tray)

            tag_uid = tray.get("tag_uid")
            if tag_uid:
                spool = conn.execute(
                    "SELECT id FROM spools WHERE bambu_tag_uid = ?", (tag_uid,)
                ).fetchone()
                if spool:
                    conn.execute(
                        """
                        UPDATE ams_slot_mappings SET spool_id = ?, updated_at = datetime('now')
                        WHERE printer_id = 1 AND slot = ?
                        """,
                        (spool["id"], int(slot_str)),
                    )
