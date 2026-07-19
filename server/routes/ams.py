"""AMS slot mapping and live tray state."""

from __future__ import annotations

from typing import Any

from bambu.filament_rfid import sync_slot_for_tray, teach_from_spool
from db import connect, row_to_dict, rows_to_dicts


def get_default_printer() -> dict[str, Any]:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM printers WHERE is_default = 1 ORDER BY id LIMIT 1"
        ).fetchone()
        if not row:
            raise KeyError("no printer configured")
        return row_to_dict(row)


def list_ams_slots(printer_id: int | None = None) -> list[dict[str, Any]]:
    with connect() as conn:
        if printer_id is None:
            printer = conn.execute(
                "SELECT id FROM printers WHERE is_default = 1 ORDER BY id LIMIT 1"
            ).fetchone()
            printer_id = printer["id"] if printer else 1
        rows = conn.execute(
            """
            SELECT m.*, s.brand, s.material, s.color_name, s.color_hex, s.remaining_g,
                   s.id AS mapped_spool_id
            FROM ams_slot_mappings m
            LEFT JOIN spools s ON s.id = m.spool_id
            WHERE m.printer_id = ?
            ORDER BY m.slot
            """,
            (printer_id,),
        ).fetchall()
        return rows_to_dicts(rows)


def update_ams_slot(slot: int, data: dict[str, Any], printer_id: int | None = None) -> dict[str, Any]:
    if slot < 1 or slot > 4:
        raise ValueError("slot must be 1-4")
    with connect() as conn:
        if printer_id is None:
            printer = conn.execute(
                "SELECT id FROM printers WHERE is_default = 1 ORDER BY id LIMIT 1"
            ).fetchone()
            printer_id = printer["id"] if printer else 1
        spool_id = data.get("spool_id")
        conn.execute(
            """
            INSERT INTO ams_slot_mappings (printer_id, slot, spool_id, updated_at)
            VALUES (?, ?, ?, datetime('now'))
            ON CONFLICT(printer_id, slot) DO UPDATE SET
                spool_id = excluded.spool_id,
                updated_at = datetime('now')
            """,
            (printer_id, slot, spool_id),
        )
        mapping = conn.execute(
            """
            SELECT mqtt_tag_uid, mqtt_tray_info_idx, mqtt_tray_type, mqtt_tray_color
            FROM ams_slot_mappings WHERE printer_id = ? AND slot = ?
            """,
            (printer_id, slot),
        ).fetchone()
        if spool_id and mapping:
            tray = {
                "tag_uid": mapping["mqtt_tag_uid"],
                "tray_info_idx": mapping["mqtt_tray_info_idx"],
                "tray_type": mapping["mqtt_tray_type"],
                "tray_color": mapping["mqtt_tray_color"],
            }
            if tray.get("tag_uid") or tray.get("tray_info_idx"):
                teach_from_spool(conn, int(spool_id), tray)
    slots = list_ams_slots(printer_id)
    return next(s for s in slots if s["slot"] == slot)


def update_mqtt_tray_state(printer_id: int, slot: int, tray: dict[str, Any]) -> None:
    with connect() as conn:
        sync_slot_for_tray(conn, printer_id, slot, tray)


def get_live_printer_state() -> dict[str, Any]:
    with connect() as conn:
        state_raw = conn.execute(
            "SELECT value FROM sync_state WHERE key = 'live_printer_state'"
        ).fetchone()
        ams_raw = conn.execute(
            "SELECT value FROM sync_state WHERE key = 'live_ams_state'"
        ).fetchone()
    import json

    state = json.loads(state_raw["value"]) if state_raw else {}
    ams = json.loads(ams_raw["value"]) if ams_raw else {}
    return {"printer": state, "ams": ams, "slots": list_ams_slots()}
