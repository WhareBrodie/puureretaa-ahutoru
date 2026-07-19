"""Process completed prints and deduct filament from mapped spools."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from bambu.filament_rfid import lookup_filament, pick_active_spool, sync_slot_for_tray
from bambu.task_guard import (
    is_before_baseline,
    is_bambu_task_ignored,
    should_deduct_auto_import,
)
from db import connect, ceil_usage_g, deduct_spool_weight, scaled_deduction_g, set_sync_state

logger = logging.getLogger("bambu.processor")


def normalize_ams_slot(value: Any) -> int:
    if value is None or value == "":
        return 1
    slot = int(value)
    if slot < 1:
        slot += 1
    return max(1, min(4, slot))


def deduct_print_usage(
    conn,
    *,
    usage_id: int,
    spool_id: int,
    used_g: float,
    completion_percent: float,
) -> float:
    row = conn.execute(
        "SELECT filament_deducted FROM print_usages WHERE id = ?",
        (usage_id,),
    ).fetchone()
    if row and row["filament_deducted"]:
        return 0.0
    grams = scaled_deduction_g(used_g, completion_percent)
    if grams <= 0:
        return 0.0
    deduct_spool_weight(conn, spool_id, grams)
    conn.execute(
        "UPDATE print_usages SET filament_deducted = 1 WHERE id = ?",
        (usage_id,),
    )
    return grams


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


def resolve_spool_from_mapped_slots(
    conn,
    printer_id: int,
    material: str | None,
    color: str | None,
) -> tuple[int | None, int | None]:
    """Pick a spool from current AMS slot mappings by material/colour."""
    rows = conn.execute(
        """
        SELECT m.slot, m.spool_id, s.material, s.color_hex, s.color_name
        FROM ams_slot_mappings m
        JOIN spools s ON s.id = m.spool_id
        WHERE m.printer_id = ? AND m.spool_id IS NOT NULL
        """,
        (printer_id,),
    ).fetchall()
    if not rows:
        return None, None

    candidates = rows
    if material:
        material = material.upper()
        filtered = [row for row in rows if (row["material"] or "").upper() == material]
        if filtered:
            candidates = filtered

    if len(candidates) == 1:
        row = candidates[0]
        return int(row["spool_id"]), int(row["slot"])

    if color:
        best = min(candidates, key=lambda row: _color_distance(color, row["color_hex"]))
        if _color_distance(color, best["color_hex"]) <= 120:
            return int(best["spool_id"]), int(best["slot"])

    return None, None


def _restore_deducted_usage(
    conn,
    *,
    usage_row: Any,
    old_spool_id: int,
    completion_percent: float,
    restored: list[dict[str, Any]],
) -> None:
    grams = scaled_deduction_g(float(usage_row["used_g"]), completion_percent)
    if grams <= 0:
        return
    conn.execute(
        """
        UPDATE spools
        SET remaining_g = COALESCE(remaining_g, 0) + ?,
            updated_at = datetime('now')
        WHERE id = ?
        """,
        (grams, old_spool_id),
    )
    restored.append({"spool_id": int(old_spool_id), "grams": grams})
    conn.execute(
        "UPDATE print_usages SET filament_deducted = 0 WHERE id = ?",
        (usage_row["id"],),
    )


def _apply_usage_relink(
    conn,
    *,
    row: Any,
    match: dict[str, Any],
    printer_id: int,
    completion_percent: float,
    restored: list[dict[str, Any]],
) -> None:
    slot = normalize_ams_slot(match.get("ams_slot"))
    spool_id = resolve_spool_for_slot(
        conn,
        printer_id,
        slot,
        match.get("material"),
        match.get("color"),
    )
    old_spool_id = row["spool_id"]
    if (
        row["filament_deducted"]
        and old_spool_id
        and spool_id
        and int(old_spool_id) != int(spool_id)
    ):
        _restore_deducted_usage(
            conn,
            usage_row=row,
            old_spool_id=int(old_spool_id),
            completion_percent=completion_percent,
            restored=restored,
        )

    conn.execute(
        """
        UPDATE print_usages
        SET ams_slot = ?, spool_id = ?, material = ?, color = ?, resolved = ?
        WHERE id = ?
        """,
        (
            slot,
            spool_id,
            match.get("material") or row["material"],
            match.get("color") or row["color"],
            1 if spool_id else 0,
            row["id"],
        ),
    )


def relink_usages_from_ams_mappings(conn, job: dict[str, Any]) -> tuple[int, list[dict[str, Any]]]:
    """Fallback when cloud task data is unavailable: match usage to mapped AMS spools."""
    pending = conn.execute(
        """
        SELECT * FROM print_usages
        WHERE print_job_id = ? AND used_g > 0
        """,
        (job["id"],),
    ).fetchall()
    if not pending:
        return 0, []

    printer_id = int(job.get("printer_id") or 1)
    completion_percent = float(job.get("completion_percent") or 100.0)
    restored: list[dict[str, Any]] = []
    updated = 0

    for row in pending:
        spool_id, slot = resolve_spool_from_mapped_slots(
            conn,
            printer_id,
            row["material"],
            row["color"],
        )
        if not spool_id or not slot:
            continue
        if row["spool_id"] and int(row["spool_id"]) == int(spool_id):
            continue
        _apply_usage_relink(
            conn,
            row=row,
            match={
                "ams_slot": slot,
                "material": row["material"],
                "color": row["color"],
            },
            printer_id=printer_id,
            completion_percent=completion_percent,
            restored=restored,
        )
        updated += 1

    return updated, restored


def refresh_cloud_print_usage_links(conn, job: dict[str, Any]) -> tuple[int, list[dict[str, Any]]]:
    """Re-resolve AMS slots/spools from Bambu cloud task data before deducting."""
    if job.get("source") != "cloud" or not job.get("bambu_task_id"):
        return 0, []

    from bambu.cloud_sync import BambuCloudClient

    cloud = BambuCloudClient()
    if not cloud.is_configured():
        return 0, []

    detail = cloud.fetch_task_for_deduction(str(job["bambu_task_id"]))
    if not detail:
        return relink_usages_from_ams_mappings(conn, job)

    fresh_usages = cloud.extract_filament_usages(detail)
    weighted_fresh = [usage for usage in fresh_usages if float(usage.get("used_g") or 0) > 0]
    if not weighted_fresh:
        return relink_usages_from_ams_mappings(conn, job)

    pending = conn.execute(
        """
        SELECT * FROM print_usages
        WHERE print_job_id = ? AND used_g > 0
        """,
        (job["id"],),
    ).fetchall()
    updated = 0
    restored: list[dict[str, Any]] = []
    printer_id = int(job.get("printer_id") or 1)
    completion_percent = float(job.get("completion_percent") or 100.0)

    for row in pending:
        match = None
        for fresh in weighted_fresh:
            if fresh.get("used_g") == row["used_g"] and (
                not row["material"]
                or row["material"] == "UNKNOWN"
                or fresh.get("material") == row["material"]
            ):
                match = fresh
                break
        if not match and len(weighted_fresh) == 1 and len(pending) == 1:
            match = weighted_fresh[0]

        if not match:
            continue

        _apply_usage_relink(
            conn,
            row=row,
            match=match,
            printer_id=printer_id,
            completion_percent=completion_percent,
            restored=restored,
        )
        updated += 1

    if updated == 0:
        return relink_usages_from_ams_mappings(conn, job)

    return updated, restored


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
            slot = normalize_ams_slot(usage.get("ams_slot"))
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
                "used_g": ceil_usage_g(float(usage.get("used_g") or 0)),
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
        skip_deduct = status in {"cancelled", "failed"} and scale <= 0
        for usage in resolved_usages:
            cur = conn.execute(
                """
                INSERT INTO print_usages (
                    print_job_id, ams_slot, spool_id, material, color, used_g, used_m, resolved,
                    filament_deducted
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
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
            usage_id = cur.lastrowid
            if (
                usage.get("spool_id")
                and deduct
                and not skip_deduct
                and float(usage.get("used_g") or 0) > 0
            ):
                deduct_print_usage(
                    conn,
                    usage_id=usage_id,
                    spool_id=int(usage["spool_id"]),
                    used_g=float(usage.get("used_g") or 0),
                    completion_percent=completion_percent,
                )

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

    # Slot mapping updates use their own transaction — never nest connect() inside the block above
    # or SQLite can lock and roll back live_ams_state even though trays were parsed.
    if trays:
        with connect() as conn:
            for slot_str, tray in trays.items():
                sync_slot_for_tray(conn, 1, int(slot_str), tray)
