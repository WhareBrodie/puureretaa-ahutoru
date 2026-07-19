"""Bambu RFID = filament product identity; active spool picked from inventory heuristics."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("bambu.filament_rfid")


def _norm(value: str | None) -> str:
    return (value or "").strip()


def _find_learned_row(
    conn,
    *,
    tag_uid: str | None,
    tray_info_idx: str | None,
) -> dict[str, Any] | None:
    tray_info_idx = _norm(tray_info_idx) or None
    tag_uid = _norm(tag_uid) or None
    if tray_info_idx:
        row = conn.execute(
            "SELECT * FROM bambu_filament_rfid WHERE tray_info_idx = ?",
            (tray_info_idx,),
        ).fetchone()
        return dict(row) if row else None
    if tag_uid:
        row = conn.execute(
            """
            SELECT * FROM bambu_filament_rfid
            WHERE tag_uid = ?
            ORDER BY CASE WHEN tray_info_idx IS NULL OR tray_info_idx = '' THEN 0 ELSE 1 END, id
            LIMIT 1
            """,
            (tag_uid,),
        ).fetchone()
        return dict(row) if row else None
    return None


def learn_filament_rfid(
    conn,
    *,
    tag_uid: str | None,
    tray_info_idx: str | None,
    brand: str,
    material: str,
    color_name: str | None,
    color_hex: str | None = None,
) -> None:
    tag_uid = _norm(tag_uid) or None
    tray_info_idx = _norm(tray_info_idx) or None
    brand = _norm(brand)
    material = _norm(material).upper()
    color_name = _norm(color_name) or None
    if not brand or not material:
        return
    if not tag_uid and not tray_info_idx:
        return

    existing = _find_learned_row(conn, tag_uid=tag_uid, tray_info_idx=tray_info_idx)
    if existing:
        conn.execute(
            """
            UPDATE bambu_filament_rfid
            SET brand = ?, material = ?, color_name = ?, color_hex = COALESCE(?, color_hex),
                tag_uid = COALESCE(?, tag_uid),
                tray_info_idx = COALESCE(?, tray_info_idx),
                learned_at = datetime('now')
            WHERE id = ?
            """,
            (brand, material, color_name, color_hex, tag_uid, tray_info_idx, existing["id"]),
        )
        logger.info("Updated Bambu RFID mapping for %s %s %s", brand, material, color_name or "")
        return

    conn.execute(
        """
        INSERT INTO bambu_filament_rfid (tag_uid, tray_info_idx, brand, material, color_name, color_hex)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (tag_uid, tray_info_idx, brand, material, color_name, color_hex),
    )
    logger.info("Learned Bambu RFID for %s %s %s", brand, material, color_name or "")


def lookup_filament(
    conn,
    *,
    tag_uid: str | None = None,
    tray_info_idx: str | None = None,
) -> dict[str, Any] | None:
    """Resolve a learned product. tray_info_idx is authoritative; never guess colour from tag_uid alone."""
    tray_info_idx = _norm(tray_info_idx) or None
    tag_uid = _norm(tag_uid) or None
    if tray_info_idx:
        row = conn.execute(
            "SELECT * FROM bambu_filament_rfid WHERE tray_info_idx = ?",
            (tray_info_idx,),
        ).fetchone()
        if row:
            return dict(row)
        return None
    if tag_uid:
        row = conn.execute(
            """
            SELECT * FROM bambu_filament_rfid
            WHERE tag_uid = ? AND (tray_info_idx IS NULL OR tray_info_idx = '')
            """,
            (tag_uid,),
        ).fetchone()
        if row:
            return dict(row)
    return None


def pick_active_spool(
    conn,
    brand: str,
    material: str,
    color_name: str | None,
) -> int | None:
    """Prefer a partially-used spool; if all are full, any match is fine."""
    rows = conn.execute(
        """
        SELECT id, remaining_g, initial_weight_g
        FROM spools
        WHERE brand = ? AND material = ? AND COALESCE(color_name, '') = COALESCE(?, '')
          AND COALESCE(remaining_g, 0) > 0
        ORDER BY id
        """,
        (_norm(brand), _norm(material).upper(), _norm(color_name) or None),
    ).fetchall()
    if not rows:
        return None

    open_spools = []
    for row in rows:
        initial = float(row["initial_weight_g"] or 1000)
        remaining = float(row["remaining_g"] or 0)
        if remaining < initial - 1:
            open_spools.append(row)

    if open_spools:
        return int(open_spools[0]["id"])
    return int(rows[0]["id"])


def teach_from_spool(conn, spool_id: int, tray: dict[str, Any]) -> None:
    spool = conn.execute(
        "SELECT brand, material, color_name, color_hex FROM spools WHERE id = ?",
        (spool_id,),
    ).fetchone()
    if not spool:
        return
    learn_filament_rfid(
        conn,
        tag_uid=tray.get("tag_uid"),
        tray_info_idx=tray.get("tray_info_idx"),
        brand=spool["brand"],
        material=spool["material"],
        color_name=spool["color_name"],
        color_hex=spool["color_hex"],
    )


def sync_slot_for_tray(conn, printer_id: int, slot: int, tray: dict[str, Any]) -> int | None:
    """Update MQTT tray fields only. Never change an assigned spool_id from MQTT — that caused dropdowns to jump."""
    conn.execute(
        """
        UPDATE ams_slot_mappings
        SET mqtt_tray_type = ?,
            mqtt_tray_color = ?,
            mqtt_tray_info_idx = ?,
            mqtt_tag_uid = ?,
            updated_at = datetime('now')
        WHERE printer_id = ? AND slot = ?
        """,
        (
            tray.get("tray_type"),
            tray.get("tray_color"),
            tray.get("tray_info_idx"),
            tray.get("tag_uid"),
            printer_id,
            slot,
        ),
    )

    mapping = conn.execute(
        "SELECT spool_id FROM ams_slot_mappings WHERE printer_id = ? AND slot = ?",
        (printer_id, slot),
    ).fetchone()

    if mapping and mapping["spool_id"]:
        return int(mapping["spool_id"])

    tag_uid = _norm(tray.get("tag_uid")) or None
    tray_info_idx = _norm(tray.get("tray_info_idx")) or None
    product = lookup_filament(conn, tag_uid=tag_uid, tray_info_idx=tray_info_idx)
    if not product:
        return None

    spool_id = pick_active_spool(
        conn,
        product["brand"],
        product["material"],
        product["color_name"],
    )
    if spool_id:
        conn.execute(
            """
            UPDATE ams_slot_mappings SET spool_id = ?, updated_at = datetime('now')
            WHERE printer_id = ? AND slot = ?
            """,
            (spool_id, printer_id, slot),
        )
    return spool_id
