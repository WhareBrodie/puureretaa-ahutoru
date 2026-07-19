"""Storage location CRUD."""

from __future__ import annotations

import sqlite3
from typing import Any

from db import connect, row_to_dict, rows_to_dicts


def list_locations() -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM storage_locations ORDER BY name COLLATE NOCASE"
        ).fetchall()
        return rows_to_dicts(rows)


def create_location(data: dict[str, Any]) -> dict[str, Any]:
    name = (data.get("name") or "").strip()
    if not name:
        raise ValueError("name is required")
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO storage_locations (name, description) VALUES (?, ?)",
            (name, data.get("description")),
        )
        location_id = cur.lastrowid
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM storage_locations WHERE id = ?", (location_id,)
        ).fetchone()
        return row_to_dict(row)


def update_location(location_id: int, data: dict[str, Any]) -> dict[str, Any]:
    with connect() as conn:
        existing = conn.execute(
            "SELECT id FROM storage_locations WHERE id = ?", (location_id,)
        ).fetchone()
        if not existing:
            raise KeyError("location not found")
        name = data.get("name")
        if name is not None:
            name = name.strip()
            if not name:
                raise ValueError("name cannot be empty")
        conn.execute(
            """
            UPDATE storage_locations
            SET name = COALESCE(?, name),
                description = COALESCE(?, description)
            WHERE id = ?
            """,
            (name, data.get("description"), location_id),
        )
        row = conn.execute(
            "SELECT * FROM storage_locations WHERE id = ?", (location_id,)
        ).fetchone()
        return row_to_dict(row)


def delete_location(location_id: int) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM storage_locations WHERE id = ?", (location_id,))
