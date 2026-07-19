"""Spool inventory CRUD and related operations."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from db import connect, deduct_spool_weight, get_data_dir, row_to_dict, rows_to_dicts, touch_spool_updated


def _spool_query(extra_where: str = "", params: tuple[Any, ...] = ()) -> str:
    return f"""
        SELECT s.*, l.name AS location_name,
               (SELECT MAX(dried_at) FROM drying_logs d WHERE d.spool_id = s.id) AS last_dried_at
        FROM spools s
        LEFT JOIN storage_locations l ON l.id = s.location_id
        {extra_where}
        ORDER BY s.updated_at DESC, s.id DESC
    """


def list_spools(material: str | None = None, low_stock_only: bool = False) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if material:
        clauses.append("s.material = ?")
        params.append(material)
    if low_stock_only:
        clauses.append(
            "COALESCE(s.remaining_g, 0) <= COALESCE(s.low_stock_threshold_g, 100)"
        )
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with connect() as conn:
        rows = conn.execute(_spool_query(where), tuple(params)).fetchall()
        return rows_to_dicts(rows)


def get_spool(spool_id: int) -> dict[str, Any]:
    with connect() as conn:
        row = conn.execute(
            _spool_query("WHERE s.id = ?"),
            (spool_id,),
        ).fetchone()
        if not row:
            raise KeyError("spool not found")
        spool = row_to_dict(row)
        drying = conn.execute(
            "SELECT * FROM drying_logs WHERE spool_id = ? ORDER BY dried_at DESC",
            (spool_id,),
        ).fetchall()
        spool["drying_logs"] = rows_to_dicts(drying)
        usages = conn.execute(
            """
            SELECT pu.*, pj.title, pj.started_at, pj.ended_at
            FROM print_usages pu
            JOIN print_jobs pj ON pj.id = pu.print_job_id
            WHERE pu.spool_id = ?
            ORDER BY pj.started_at DESC
            LIMIT 50
            """,
            (spool_id,),
        ).fetchall()
        spool["usage_history"] = rows_to_dicts(usages)
        return spool


def _normalize_hex(color_hex: str | None) -> str | None:
    if not color_hex:
        return None
    value = color_hex.strip().lstrip("#")
    if len(value) == 6:
        return f"#{value.upper()}"
    if len(value) == 8:
        return f"#{value[:6].upper()}"
    return color_hex


def create_spool(data: dict[str, Any]) -> dict[str, Any]:
    brand = (data.get("brand") or "").strip()
    material = (data.get("material") or "").strip()
    if not brand or not material:
        raise ValueError("brand and material are required")

    qr_code_id = data.get("qr_code_id") or str(uuid.uuid4())[:8].upper()
    remaining = data.get("remaining_g")
    initial = data.get("initial_weight_g") or 1000
    if remaining is None:
        remaining = initial

    with connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO spools (
                brand, material, color_name, color_hex, purchase_price, purchase_date,
                supplier, batch_number, rating, location_id, remaining_g, initial_weight_g,
                empty_spool_weight_g, nfc_tag_id, qr_code_id, bambu_tag_uid, bambu_tray_info_idx,
                notes, low_stock_threshold_g
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                brand,
                material.upper(),
                data.get("color_name"),
                _normalize_hex(data.get("color_hex")),
                data.get("purchase_price"),
                data.get("purchase_date"),
                data.get("supplier"),
                data.get("batch_number"),
                data.get("rating"),
                data.get("location_id"),
                remaining,
                initial,
                data.get("empty_spool_weight_g"),
                data.get("nfc_tag_id"),
                qr_code_id,
                data.get("bambu_tag_uid"),
                data.get("bambu_tray_info_idx"),
                data.get("notes"),
                data.get("low_stock_threshold_g") or 100,
            ),
        )
        spool_id = cur.lastrowid
    return get_spool(spool_id)


def update_spool(spool_id: int, data: dict[str, Any]) -> dict[str, Any]:
    with connect() as conn:
        existing = conn.execute("SELECT id FROM spools WHERE id = ?", (spool_id,)).fetchone()
        if not existing:
            raise KeyError("spool not found")

        fields = {
            "brand": data.get("brand"),
            "material": data.get("material").upper() if data.get("material") else None,
            "color_name": data.get("color_name"),
            "color_hex": _normalize_hex(data.get("color_hex")) if data.get("color_hex") else data.get("color_hex"),
            "purchase_price": data.get("purchase_price"),
            "purchase_date": data.get("purchase_date"),
            "supplier": data.get("supplier"),
            "batch_number": data.get("batch_number"),
            "rating": data.get("rating"),
            "location_id": data.get("location_id"),
            "remaining_g": data.get("remaining_g"),
            "initial_weight_g": data.get("initial_weight_g"),
            "empty_spool_weight_g": data.get("empty_spool_weight_g"),
            "nfc_tag_id": data.get("nfc_tag_id"),
            "bambu_tag_uid": data.get("bambu_tag_uid"),
            "bambu_tray_info_idx": data.get("bambu_tray_info_idx"),
            "notes": data.get("notes"),
            "low_stock_threshold_g": data.get("low_stock_threshold_g"),
        }
        assignments = []
        values: list[Any] = []
        for key, value in fields.items():
            if key in data:
                assignments.append(f"{key} = ?")
                values.append(value)
        if assignments:
            assignments.append("updated_at = datetime('now')")
            values.append(spool_id)
            conn.execute(
                f"UPDATE spools SET {', '.join(assignments)} WHERE id = ?",
                values,
            )
    return get_spool(spool_id)


def delete_spool(spool_id: int) -> None:
    with connect() as conn:
        row = conn.execute("SELECT photo_path FROM spools WHERE id = ?", (spool_id,)).fetchone()
        if row and row["photo_path"]:
            photo = get_data_dir() / row["photo_path"]
            if photo.is_file():
                photo.unlink(missing_ok=True)
        conn.execute("DELETE FROM spools WHERE id = ?", (spool_id,))


def calculate_remaining_from_scale(spool_id: int, total_weight_g: float) -> dict[str, Any]:
    if total_weight_g <= 0:
        raise ValueError("total_weight_g must be positive")
    with connect() as conn:
        row = conn.execute(
            "SELECT empty_spool_weight_g, brand, material FROM spools WHERE id = ?",
            (spool_id,),
        ).fetchone()
        if not row:
            raise KeyError("spool not found")
        empty_weight = row["empty_spool_weight_g"]
        if empty_weight is None:
            guess = conn.execute(
                """
                SELECT weight_g FROM empty_spool_weights
                WHERE brand = ? OR brand = 'Generic'
                ORDER BY CASE WHEN brand = ? THEN 0 ELSE 1 END
                LIMIT 1
                """,
                (row["brand"], row["brand"]),
            ).fetchone()
            empty_weight = guess["weight_g"] if guess else 250
        remaining = max(0.0, total_weight_g - empty_weight)
        conn.execute(
            "UPDATE spools SET remaining_g = ?, empty_spool_weight_g = ?, updated_at = datetime('now') WHERE id = ?",
            (remaining, empty_weight, spool_id),
        )
    return get_spool(spool_id)


def add_drying_log(spool_id: int, data: dict[str, Any]) -> dict[str, Any]:
    dried_at = data.get("dried_at") or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with connect() as conn:
        if not conn.execute("SELECT id FROM spools WHERE id = ?", (spool_id,)).fetchone():
            raise KeyError("spool not found")
        conn.execute(
            "INSERT INTO drying_logs (spool_id, dried_at, notes) VALUES (?, ?, ?)",
            (spool_id, dried_at, data.get("notes")),
        )
        touch_spool_updated(conn, spool_id)
    return get_spool(spool_id)


def save_photo(spool_id: int, filename: str, content: bytes) -> dict[str, Any]:
    ext = Path(filename).suffix.lower() or ".jpg"
    if ext not in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        raise ValueError("unsupported image type")
    rel_path = f"photos/spool_{spool_id}{ext}"
    abs_path = get_data_dir() / rel_path
    abs_path.write_bytes(content)
    with connect() as conn:
        old = conn.execute("SELECT photo_path FROM spools WHERE id = ?", (spool_id,)).fetchone()
        if old and old["photo_path"] and old["photo_path"] != rel_path:
            old_path = get_data_dir() / old["photo_path"]
            if old_path.is_file():
                old_path.unlink(missing_ok=True)
        conn.execute(
            "UPDATE spools SET photo_path = ?, updated_at = datetime('now') WHERE id = ?",
            (rel_path, spool_id),
        )
    return get_spool(spool_id)


def lookup_empty_spool_weights(brand: str | None = None, model: str | None = None) -> list[dict[str, Any]]:
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
            f"SELECT * FROM empty_spool_weights {where} ORDER BY brand, model",
            tuple(params),
        ).fetchall()
        return rows_to_dicts(rows)


def find_spool_by_bambu_tag(tag_uid: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute(
            _spool_query("WHERE s.bambu_tag_uid = ?"),
            (tag_uid,),
        ).fetchone()
        return row_to_dict(row) if row else None


def link_bambu_tag(spool_id: int, tag_uid: str, tray_info_idx: str | None = None) -> dict[str, Any]:
    with connect() as conn:
        conn.execute(
            """
            UPDATE spools SET bambu_tag_uid = ?, bambu_tray_info_idx = COALESCE(?, bambu_tray_info_idx),
            updated_at = datetime('now') WHERE id = ?
            """,
            (tag_uid, tray_info_idx, spool_id),
        )
    return get_spool(spool_id)
