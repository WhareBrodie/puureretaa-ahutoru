"""Filament type edits — bulk-update all spools sharing brand + material + colour."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote

from db import connect, get_data_dir, row_to_dict
from routes.spools import _normalize_hex

ALLOWED_LABEL_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".pdf"}


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


def _label_color_key(color_name: str | None) -> str:
    return color_name or ""


def _label_file_hash(brand: str, material: str, color_name: str | None) -> str:
    raw = f"{brand}|{material}|{_label_color_key(color_name)}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def _label_rel_path(brand: str, material: str, color_name: str | None, ext: str) -> str:
    return f"labels/filament_{_label_file_hash(brand, material, color_name)}{ext}"


def _ensure_filament_exists(conn: Any, brand: str, material: str, color_name: str | None) -> None:
    row = conn.execute(
        """
        SELECT COUNT(*) AS n FROM spools
        WHERE brand = ? AND material = ? AND COALESCE(color_name, '') = COALESCE(?, '')
        """,
        (brand, material, color_name),
    ).fetchone()
    if not row or row["n"] == 0:
        raise KeyError("filament not found")


def _label_meta(row: dict[str, Any] | None) -> dict[str, Any]:
    if not row:
        return {"has_label": False}
    filename = Path(row["file_path"]).name
    return {
        "has_label": True,
        "original_filename": row.get("original_filename") or filename,
        "uploaded_at": row.get("uploaded_at"),
        "file_path": row["file_path"],
        "url": f"/api/labels/{filename}",
        "content_type": _guess_content_type(filename),
    }


def _guess_content_type(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".pdf": "application/pdf",
    }.get(ext, "application/octet-stream")


def get_label(key: str) -> dict[str, Any]:
    brand, material, color_name = parse_filament_key(key)
    with connect() as conn:
        _ensure_filament_exists(conn, brand, material, color_name)
        row = conn.execute(
            """
            SELECT * FROM filament_labels
            WHERE brand = ? AND material = ? AND color_name = ?
            """,
            (brand, material, _label_color_key(color_name)),
        ).fetchone()
    return _label_meta(row_to_dict(row) if row else None)


def save_label(key: str, filename: str, content: bytes) -> dict[str, Any]:
    brand, material, color_name = parse_filament_key(key)
    ext = Path(filename).suffix.lower() or ".png"
    if ext not in ALLOWED_LABEL_EXTS:
        raise ValueError("unsupported label type (use png, jpg, webp, or pdf)")
    if not content:
        raise ValueError("empty file")

    rel_path = _label_rel_path(brand, material, color_name, ext)
    abs_path = get_data_dir() / rel_path
    abs_path.parent.mkdir(parents=True, exist_ok=True)

    with connect() as conn:
        _ensure_filament_exists(conn, brand, material, color_name)
        old = conn.execute(
            """
            SELECT * FROM filament_labels
            WHERE brand = ? AND material = ? AND color_name = ?
            """,
            (brand, material, _label_color_key(color_name)),
        ).fetchone()
        if old and old["file_path"] and old["file_path"] != rel_path:
            old_path = get_data_dir() / old["file_path"]
            if old_path.is_file():
                old_path.unlink(missing_ok=True)

        abs_path.write_bytes(content)
        original = Path(filename).name or f"label{ext}"
        conn.execute(
            """
            INSERT INTO filament_labels (brand, material, color_name, file_path, original_filename, uploaded_at)
            VALUES (?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(brand, material, color_name) DO UPDATE SET
              file_path = excluded.file_path,
              original_filename = excluded.original_filename,
              uploaded_at = datetime('now')
            """,
            (brand, material, _label_color_key(color_name), rel_path, original),
        )
        row = conn.execute(
            """
            SELECT * FROM filament_labels
            WHERE brand = ? AND material = ? AND color_name = ?
            """,
            (brand, material, _label_color_key(color_name)),
        ).fetchone()
    return _label_meta(row_to_dict(row) if row else None)


def delete_label(key: str) -> dict[str, Any]:
    brand, material, color_name = parse_filament_key(key)
    with connect() as conn:
        _ensure_filament_exists(conn, brand, material, color_name)
        row = conn.execute(
            """
            SELECT * FROM filament_labels
            WHERE brand = ? AND material = ? AND color_name = ?
            """,
            (brand, material, _label_color_key(color_name)),
        ).fetchone()
        if not row:
            raise KeyError("label not found")
        conn.execute(
            "DELETE FROM filament_labels WHERE brand = ? AND material = ? AND color_name = ?",
            (brand, material, _label_color_key(color_name)),
        )
    file_path = get_data_dir() / row["file_path"]
    if file_path.is_file():
        file_path.unlink(missing_ok=True)
    return {"ok": True, "has_label": False}


def _rekey_label(
    conn: Any,
    old_brand: str,
    old_material: str,
    old_color_name: str | None,
    new_brand: str,
    new_material: str,
    new_color_name: str | None,
) -> None:
    old_key = _label_color_key(old_color_name)
    new_key = _label_color_key(new_color_name)
    if (old_brand, old_material, old_key) == (new_brand, new_material, new_key):
        return

    row = conn.execute(
        """
        SELECT * FROM filament_labels
        WHERE brand = ? AND material = ? AND color_name = ?
        """,
        (old_brand, old_material, old_key),
    ).fetchone()
    if not row:
        return

    old_path = Path(row["file_path"])
    ext = old_path.suffix.lower() or ".png"
    new_rel = _label_rel_path(new_brand, new_material, new_color_name, ext)
    data_dir = get_data_dir()
    src = data_dir / row["file_path"]
    dst = data_dir / new_rel
    if src.is_file() and src.resolve() != dst.resolve():
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.replace(dst)

    # Drop any conflicting row for the new key (shouldn't happen after spool rename collision checks).
    conn.execute(
        """
        DELETE FROM filament_labels
        WHERE brand = ? AND material = ? AND color_name = ?
          AND NOT (brand = ? AND material = ? AND color_name = ?)
        """,
        (new_brand, new_material, new_key, old_brand, old_material, old_key),
    )
    conn.execute(
        """
        UPDATE filament_labels
        SET brand = ?, material = ?, color_name = ?, file_path = ?
        WHERE brand = ? AND material = ? AND color_name = ?
        """,
        (new_brand, new_material, new_key, new_rel, old_brand, old_material, old_key),
    )


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

        _rekey_label(
            conn,
            old_brand,
            old_material,
            old_color_name,
            new_brand,
            new_material,
            new_color_name,
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
