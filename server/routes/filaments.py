"""Filament type edits — bulk-update all spools sharing brand + material + colour."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote, unquote

from db import connect
from routes.spools import _normalize_hex


def parse_filament_key(key: str) -> tuple[str, str, str | None]:
    decoded = unquote(key)
    parts = decoded.split("|", 2)
    if len(parts) < 2:
        raise ValueError("invalid filament key")
    brand, material = parts[0], parts[1]
    color_name = parts[2] if len(parts) > 2 and parts[2] else None
    return brand, material, color_name


def make_filament_key(brand: str, material: str, color_name: str | None) -> str:
    return quote("|".join([brand, material, color_name or ""]), safe="")


def update_filament(key: str, data: dict[str, Any]) -> dict[str, Any]:
    old_brand, old_material, old_color_name = parse_filament_key(key)

    new_brand = (data.get("brand") if "brand" in data else old_brand).strip()
    new_material = (
        (data.get("material") if "material" in data else old_material).strip().upper()
    )
    new_color_name = data.get("color_name") if "color_name" in data else old_color_name
    if new_color_name is not None:
        new_color_name = new_color_name.strip() or None

    if not new_brand or not new_material:
        raise ValueError("brand and material are required")

    update_color_hex = "color_hex" in data
    new_color_hex = (
        _normalize_hex(data["color_hex"]) if data.get("color_hex") else None
        if update_color_hex
        else None
    )

    with connect() as conn:
        count_row = conn.execute(
            """
            SELECT COUNT(*) AS n FROM spools
            WHERE brand = ? AND material = ? AND COALESCE(color_name, '') = COALESCE(?, '')
            """,
            (old_brand, old_material, old_color_name),
        ).fetchone()
        if not count_row or count_row["n"] == 0:
            raise KeyError("filament not found")

        if update_color_hex:
            conn.execute(
                """
                UPDATE spools
                SET brand = ?, material = ?, color_name = ?, color_hex = ?,
                    updated_at = datetime('now')
                WHERE brand = ? AND material = ? AND COALESCE(color_name, '') = COALESCE(?, '')
                """,
                (
                    new_brand,
                    new_material,
                    new_color_name,
                    new_color_hex,
                    old_brand,
                    old_material,
                    old_color_name,
                ),
            )
        else:
            conn.execute(
                """
                UPDATE spools
                SET brand = ?, material = ?, color_name = ?,
                    updated_at = datetime('now')
                WHERE brand = ? AND material = ? AND COALESCE(color_name, '') = COALESCE(?, '')
                """,
                (
                    new_brand,
                    new_material,
                    new_color_name,
                    old_brand,
                    old_material,
                    old_color_name,
                ),
            )

        if update_color_hex:
            conn.execute(
                """
                UPDATE bambu_filament_rfid
                SET brand = ?, material = ?, color_name = ?, color_hex = ?,
                    learned_at = datetime('now')
                WHERE brand = ? AND material = ? AND COALESCE(color_name, '') = COALESCE(?, '')
                """,
                (
                    new_brand,
                    new_material,
                    new_color_name,
                    new_color_hex,
                    old_brand,
                    old_material,
                    old_color_name,
                ),
            )
        else:
            conn.execute(
                """
                UPDATE bambu_filament_rfid
                SET brand = ?, material = ?, color_name = ?,
                    learned_at = datetime('now')
                WHERE brand = ? AND material = ? AND COALESCE(color_name, '') = COALESCE(?, '')
                """,
                (
                    new_brand,
                    new_material,
                    new_color_name,
                    old_brand,
                    old_material,
                    old_color_name,
                ),
            )

        sample = conn.execute(
            """
            SELECT color_hex FROM spools
            WHERE brand = ? AND material = ? AND COALESCE(color_name, '') = COALESCE(?, '')
            LIMIT 1
            """,
            (new_brand, new_material, new_color_name),
        ).fetchone()

    return {
        "brand": new_brand,
        "material": new_material,
        "color_name": new_color_name,
        "color_hex": sample["color_hex"] if sample else None,
        "key": make_filament_key(new_brand, new_material, new_color_name),
        "updated_spool_count": int(count_row["n"]),
    }
