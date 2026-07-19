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
               e.brand AS empty_spool_brand, e.model AS empty_spool_model,
               (SELECT MAX(dried_at) FROM drying_logs d WHERE d.spool_id = s.id) AS last_dried_at
        FROM spools s
        LEFT JOIN storage_locations l ON l.id = s.location_id
        LEFT JOIN empty_spool_weights e ON e.id = s.empty_spool_weight_id
        {extra_where}
        ORDER BY s.updated_at DESC, s.id DESC
    """


def _default_empty_spool_profile(conn: sqlite3.Connection, brand: str) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT id, weight_g FROM empty_spool_weights
        WHERE brand = ? OR brand = 'Generic'
        ORDER BY CASE WHEN brand = ? THEN 0 ELSE 1 END, id
        LIMIT 1
        """,
        (brand, brand),
    ).fetchone()


def resolve_empty_spool_weight(
    conn: sqlite3.Connection,
    *,
    brand: str,
    empty_spool_weight_g: float | None = None,
    empty_spool_weight_id: int | None = None,
) -> tuple[float, int | None]:
    if empty_spool_weight_id:
        row = conn.execute(
            "SELECT id, weight_g FROM empty_spool_weights WHERE id = ?",
            (empty_spool_weight_id,),
        ).fetchone()
        if row:
            return float(row["weight_g"]), int(row["id"])
    if empty_spool_weight_g is not None:
        return float(empty_spool_weight_g), empty_spool_weight_id
    guess = _default_empty_spool_profile(conn, brand)
    if guess:
        return float(guess["weight_g"]), int(guess["id"])
    return 250.0, None


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
        usage_rows = rows_to_dicts(usages)
        price = spool.get("purchase_price")
        initial = spool.get("initial_weight_g")
        for usage in usage_rows:
            used = usage.get("used_g")
            if price is not None and initial and initial > 0 and used:
                usage["cost"] = round(used * (price / initial), 2)
            else:
                usage["cost"] = None
        spool["usage_history"] = usage_rows
        return spool


def _normalize_hex(color_hex: str | None) -> str | None:
    if not color_hex:
        return None
    value = color_hex.strip()
    if value.startswith("{"):
        return value
    bare = value.lstrip("#")
    if len(bare) == 6:
        return f"#{bare.upper()}"
    if len(bare) == 8:
        return f"#{bare[:6].upper()}"
    return color_hex


def create_spool(data: dict[str, Any]) -> dict[str, Any]:
    brand = (data.get("brand") or "").strip()
    material = (data.get("material") or "").strip()
    if not brand or not material:
        raise ValueError("brand and material are required")

    qr_code_id = data.get("qr_code_id") or str(uuid.uuid4()).hex[:12].upper()
    remaining = data.get("remaining_g")
    initial = data.get("initial_weight_g") or 1000
    if remaining is None:
        remaining = initial

    with connect() as conn:
        empty_spool_weight_id = data.get("empty_spool_weight_id")
        empty_spool_weight_g = data.get("empty_spool_weight_g")
        resolved_empty, resolved_profile_id = resolve_empty_spool_weight(
            conn,
            brand=brand,
            empty_spool_weight_g=empty_spool_weight_g,
            empty_spool_weight_id=int(empty_spool_weight_id) if empty_spool_weight_id else None,
        )
        if empty_spool_weight_id is None and empty_spool_weight_g is None:
            empty_spool_weight_id = resolved_profile_id
            empty_spool_weight_g = resolved_empty
        elif empty_spool_weight_id:
            empty_spool_weight_g = resolved_empty
        cur = conn.execute(
            """
            INSERT INTO spools (
                brand, material, color_name, color_hex, purchase_price, purchase_date,
                supplier, batch_number, rating, location_id, remaining_g, initial_weight_g,
                empty_spool_weight_g, empty_spool_weight_id, nfc_tag_id, qr_code_id, bambu_tag_uid, bambu_tray_info_idx,
                notes, low_stock_threshold_g
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                empty_spool_weight_g if empty_spool_weight_g is not None else resolved_empty,
                empty_spool_weight_id if empty_spool_weight_id is not None else resolved_profile_id,
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
        existing = conn.execute(
            "SELECT brand, empty_spool_weight_g, empty_spool_weight_id FROM spools WHERE id = ?",
            (spool_id,),
        ).fetchone()
        if not existing:
            raise KeyError("spool not found")

        payload = dict(data)
        if "empty_spool_weight_id" in payload or "empty_spool_weight_g" in payload:
            resolved_empty, resolved_profile_id = resolve_empty_spool_weight(
                conn,
                brand=(payload.get("brand") or existing["brand"]),
                empty_spool_weight_g=payload.get("empty_spool_weight_g", existing["empty_spool_weight_g"]),
                empty_spool_weight_id=(
                    int(payload["empty_spool_weight_id"])
                    if payload.get("empty_spool_weight_id")
                    else existing["empty_spool_weight_id"]
                ),
            )
            payload["empty_spool_weight_g"] = resolved_empty
            payload["empty_spool_weight_id"] = resolved_profile_id

        fields = {
            "brand": payload.get("brand"),
            "material": payload.get("material").upper() if payload.get("material") else None,
            "color_name": payload.get("color_name"),
            "color_hex": _normalize_hex(payload.get("color_hex")) if payload.get("color_hex") else payload.get("color_hex"),
            "purchase_price": payload.get("purchase_price"),
            "purchase_date": payload.get("purchase_date"),
            "supplier": payload.get("supplier"),
            "batch_number": payload.get("batch_number"),
            "rating": payload.get("rating"),
            "location_id": payload.get("location_id"),
            "remaining_g": payload.get("remaining_g"),
            "initial_weight_g": payload.get("initial_weight_g"),
            "empty_spool_weight_g": payload.get("empty_spool_weight_g"),
            "empty_spool_weight_id": payload.get("empty_spool_weight_id"),
            "nfc_tag_id": payload.get("nfc_tag_id"),
            "bambu_tag_uid": payload.get("bambu_tag_uid"),
            "bambu_tray_info_idx": payload.get("bambu_tray_info_idx"),
            "notes": payload.get("notes"),
            "low_stock_threshold_g": payload.get("low_stock_threshold_g"),
        }
        assignments = []
        values: list[Any] = []
        for key, value in fields.items():
            if key in payload:
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
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with connect() as conn:
        row = conn.execute(
            """
            SELECT empty_spool_weight_g, empty_spool_weight_id, brand
            FROM spools WHERE id = ?
            """,
            (spool_id,),
        ).fetchone()
        if not row:
            raise KeyError("spool not found")
        empty_weight, profile_id = resolve_empty_spool_weight(
            conn,
            brand=row["brand"],
            empty_spool_weight_g=row["empty_spool_weight_g"],
            empty_spool_weight_id=row["empty_spool_weight_id"],
        )
        remaining = max(0.0, total_weight_g - empty_weight)
        conn.execute(
            """
            UPDATE spools
            SET remaining_g = ?, empty_spool_weight_g = ?, empty_spool_weight_id = ?,
                last_weighed_at = ?, updated_at = datetime('now')
            WHERE id = ?
            """,
            (remaining, empty_weight, profile_id, now, spool_id),
        )
    spool = get_spool(spool_id)
    spool["scale_calculation"] = {
        "total_weight_g": total_weight_g,
        "empty_spool_weight_g": empty_weight,
        "filament_remaining_g": remaining,
    }
    return spool


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
    from routes.empty_spool_weights import list_profiles

    return list_profiles(brand=brand, model=model)


def find_spool_by_bambu_tag(tag_uid: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute(
            _spool_query("WHERE s.bambu_tag_uid = ?"),
            (tag_uid,),
        ).fetchone()
        return row_to_dict(row) if row else None


def get_spool_id_by_qr_code(qr_code_id: str) -> int | None:
    with connect() as conn:
        row = conn.execute("SELECT id FROM spools WHERE qr_code_id = ?", (qr_code_id,)).fetchone()
        return row["id"] if row else None


def link_bambu_tag(spool_id: int, tag_uid: str, tray_info_idx: str | None = None) -> dict[str, Any]:
    """Learn Bambu RFID as a filament product identifier (shared across spools of same SKU)."""
    from bambu.filament_rfid import learn_filament_rfid

    with connect() as conn:
        spool = conn.execute(
            "SELECT brand, material, color_name, color_hex FROM spools WHERE id = ?",
            (spool_id,),
        ).fetchone()
        if not spool:
            raise KeyError("spool not found")
        learn_filament_rfid(
            conn,
            tag_uid=tag_uid,
            tray_info_idx=tray_info_idx,
            brand=spool["brand"],
            material=spool["material"],
            color_name=spool["color_name"],
            color_hex=spool["color_hex"],
        )
    return get_spool(spool_id)
