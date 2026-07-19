"""Empty spool weight profile CRUD."""

from __future__ import annotations

from typing import Any

from db import connect, row_to_dict, rows_to_dicts


def list_profiles(brand: str | None = None, model: str | None = None) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if brand:
        clauses.append("brand LIKE ?")
        params.append(f"%{brand}%")
    if model:
        clauses.append("model LIKE ?")
        params.append(f"%{model}%")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM empty_spool_weights {where} ORDER BY brand, model, id",
            tuple(params),
        ).fetchall()
        return rows_to_dicts(rows)


def create_profile(data: dict[str, Any]) -> dict[str, Any]:
    brand = (data.get("brand") or "").strip()
    weight_g = data.get("weight_g")
    if not brand:
        raise ValueError("brand is required")
    if weight_g is None or float(weight_g) <= 0:
        raise ValueError("weight_g must be positive")
    with connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO empty_spool_weights (brand, model, weight_g, notes)
            VALUES (?, ?, ?, ?)
            """,
            (brand, (data.get("model") or "").strip() or None, float(weight_g), data.get("notes")),
        )
        profile_id = cur.lastrowid
        row = conn.execute(
            "SELECT * FROM empty_spool_weights WHERE id = ?",
            (profile_id,),
        ).fetchone()
        return row_to_dict(row)


def update_profile(profile_id: int, data: dict[str, Any]) -> dict[str, Any]:
    with connect() as conn:
        existing = conn.execute(
            "SELECT id FROM empty_spool_weights WHERE id = ?",
            (profile_id,),
        ).fetchone()
        if not existing:
            raise KeyError("empty spool profile not found")

        fields = {
            "brand": data.get("brand"),
            "model": data.get("model"),
            "weight_g": float(data["weight_g"]) if data.get("weight_g") is not None else None,
            "notes": data.get("notes"),
        }
        assignments = []
        values: list[Any] = []
        for key, value in fields.items():
            if key in data:
                if key == "brand" and not str(value or "").strip():
                    raise ValueError("brand is required")
                if key == "weight_g" and value is not None and value <= 0:
                    raise ValueError("weight_g must be positive")
                assignments.append(f"{key} = ?")
                values.append(value.strip() if key == "brand" and isinstance(value, str) else value)
        if assignments:
            values.append(profile_id)
            conn.execute(
                f"UPDATE empty_spool_weights SET {', '.join(assignments)} WHERE id = ?",
                values,
            )
            conn.execute(
                """
                UPDATE spools
                SET empty_spool_weight_g = (
                    SELECT weight_g FROM empty_spool_weights WHERE id = spools.empty_spool_weight_id
                )
                WHERE empty_spool_weight_id = ?
                """,
                (profile_id,),
            )
        row = conn.execute(
            "SELECT * FROM empty_spool_weights WHERE id = ?",
            (profile_id,),
        ).fetchone()
        return row_to_dict(row)


def delete_profile(profile_id: int) -> None:
    with connect() as conn:
        row = conn.execute(
            "SELECT id FROM empty_spool_weights WHERE id = ?",
            (profile_id,),
        ).fetchone()
        if not row:
            raise KeyError("empty spool profile not found")
        conn.execute(
            "UPDATE spools SET empty_spool_weight_id = NULL WHERE empty_spool_weight_id = ?",
            (profile_id,),
        )
        conn.execute("DELETE FROM empty_spool_weights WHERE id = ?", (profile_id,))
