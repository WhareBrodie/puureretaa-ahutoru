"""AMS slot mapping and live tray state."""

from __future__ import annotations

from typing import Any

from bambu.filament_rfid import lookup_filament, sync_slot_for_tray, teach_from_spool
from db import connect, row_to_dict, rows_to_dicts


def _normalize_tray_color(value: str | None) -> str | None:
    if not value:
        return None
    raw = str(value).strip().lstrip("#")[:6]
    if len(raw) != 6:
        return None
    try:
        int(raw, 16)
    except ValueError:
        return None
    return raw.upper()


def _color_distance(hex_a: str | None, hex_b: str | None) -> int:
    if not hex_a or not hex_b:
        return 999
    try:
        ar, ag, ab = int(hex_a[0:2], 16), int(hex_a[2:4], 16), int(hex_a[4:6], 16)
        br, bg, bb = int(hex_b[0:2], 16), int(hex_b[2:4], 16), int(hex_b[4:6], 16)
        return abs(ar - br) + abs(ag - bg) + abs(ab - bb)
    except ValueError:
        return 999


def resolve_mapping_status(
    slot: dict[str, Any],
    live_tray: dict[str, Any] | None,
    conn=None,
) -> dict[str, str | None]:
    spool_id = slot.get("spool_id") or slot.get("mapped_spool_id")
    tray = live_tray or {}
    tray_type = (tray.get("tray_type") or slot.get("mqtt_tray_type") or "").strip().upper()
    tray_color = _normalize_tray_color(tray.get("tray_color") or slot.get("mqtt_tray_color"))
    mapped_material = (slot.get("material") or "").strip().upper()
    mapped_color = _normalize_tray_color(slot.get("color_hex"))

    if not spool_id:
        return {
            "mapping_status": "unmapped",
            "mapping_message": "Unmapped spool — pick from the dropdown",
        }

    has_tray_signal = bool(
        tray_type
        or tray_color
        or tray.get("tray_info_idx")
        or slot.get("mqtt_tray_info_idx")
        or tray.get("tag_uid")
        or slot.get("mqtt_tag_uid")
    )
    if not has_tray_signal:
        return {"mapping_status": "mapped", "mapping_message": None}

    tray_info_idx = (tray.get("tray_info_idx") or slot.get("mqtt_tray_info_idx") or "").strip()
    if tray_info_idx and conn and slot.get("brand"):
        product = lookup_filament(conn, tray_info_idx=tray_info_idx)
        if product:
            if (
                product["brand"] != slot.get("brand")
                or product["material"].upper() != mapped_material
                or (product.get("color_name") or "") != (slot.get("color_name") or "")
            ):
                return {
                    "mapping_status": "mismatch",
                    "mapping_message": "Filament in slot changed — remap spool",
                }

    if tray_type and mapped_material and tray_type not in {mapped_material, "UNKNOWN"}:
        return {
            "mapping_status": "mismatch",
            "mapping_message": "Filament in slot changed — remap spool",
        }

    if tray_color and mapped_color and _color_distance(tray_color, mapped_color) > 120:
        return {
            "mapping_status": "mismatch",
            "mapping_message": "Filament in slot changed — remap spool",
        }

    return {"mapping_status": "mapped", "mapping_message": None}


def enrich_slots_with_mapping_status(
    slots: list[dict[str, Any]],
    ams_live: dict[str, Any],
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    with connect() as conn:
        for slot in slots:
            tray = ams_live.get(str(slot["slot"])) or ams_live.get(slot["slot"]) or {}
            enriched.append({**slot, **resolve_mapping_status(slot, tray, conn)})
    return enriched


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
                   s.last_weighed_at, s.id AS mapped_spool_id
            FROM ams_slot_mappings m
            LEFT JOIN spools s ON s.id = m.spool_id
            WHERE m.printer_id = ?
            ORDER BY m.slot
            """,
            (printer_id,),
        ).fetchall()
        return rows_to_dicts(rows)


def clear_rfid_learns() -> dict[str, int]:
    with connect() as conn:
        cur = conn.execute("DELETE FROM bambu_filament_rfid")
        return {"deleted": cur.rowcount}


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
        tray_override = data.get("tray") if isinstance(data.get("tray"), dict) else None
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
        if spool_id:
            tray = tray_override or {
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
    slots = enrich_slots_with_mapping_status(list_ams_slots(), ams)
    return {"printer": state, "ams": ams, "slots": slots}


def refresh_from_printer() -> dict[str, Any]:
    from bambu.mqtt_probe import probe_printer_mqtt

    probe = probe_printer_mqtt()
    live = get_live_printer_state()
    return {"probe": probe, **live}
