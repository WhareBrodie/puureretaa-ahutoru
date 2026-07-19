"""CSV import and export."""

from __future__ import annotations

import csv
import io
from typing import Any

from db import connect, rows_to_dicts
from routes.spools import create_spool, update_spool


EXPORT_FIELDS = [
    "id",
    "brand",
    "material",
    "color_name",
    "color_hex",
    "purchase_price",
    "purchase_date",
    "supplier",
    "batch_number",
    "rating",
    "remaining_g",
    "initial_weight_g",
    "empty_spool_weight_g",
    "location_id",
    "notes",
    "low_stock_threshold_g",
    "bambu_tag_uid",
    "qr_code_id",
]


def export_spools_csv() -> str:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT id, brand, material, color_name, color_hex, purchase_price, purchase_date,
                   supplier, batch_number, rating, remaining_g, initial_weight_g, empty_spool_weight_g,
                   location_id, notes, low_stock_threshold_g, bambu_tag_uid, qr_code_id
            FROM spools ORDER BY id
            """
        ).fetchall()
        data = rows_to_dicts(rows)
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=EXPORT_FIELDS)
    writer.writeheader()
    for row in data:
        writer.writerow({field: row.get(field, "") for field in EXPORT_FIELDS})
    return output.getvalue()


def import_spools_csv(csv_text: str, update_existing: bool = False) -> dict[str, Any]:
    reader = csv.DictReader(io.StringIO(csv_text))
    created = 0
    updated = 0
    errors: list[str] = []

    for index, row in enumerate(reader, start=2):
        try:
            payload = {
                "brand": row.get("brand", "").strip(),
                "material": row.get("material", "").strip(),
                "color_name": row.get("color_name") or None,
                "color_hex": row.get("color_hex") or None,
                "purchase_price": float(row["purchase_price"]) if row.get("purchase_price") else None,
                "purchase_date": row.get("purchase_date") or None,
                "supplier": row.get("supplier") or None,
                "batch_number": row.get("batch_number") or None,
                "rating": int(row["rating"]) if row.get("rating") else None,
                "remaining_g": float(row["remaining_g"]) if row.get("remaining_g") else None,
                "initial_weight_g": float(row["initial_weight_g"]) if row.get("initial_weight_g") else None,
                "empty_spool_weight_g": float(row["empty_spool_weight_g"]) if row.get("empty_spool_weight_g") else None,
                "location_id": int(row["location_id"]) if row.get("location_id") else None,
                "notes": row.get("notes") or None,
                "low_stock_threshold_g": float(row["low_stock_threshold_g"]) if row.get("low_stock_threshold_g") else None,
                "bambu_tag_uid": row.get("bambu_tag_uid") or None,
                "qr_code_id": row.get("qr_code_id") or None,
            }
            spool_id = row.get("id")
            if update_existing and spool_id:
                update_spool(int(spool_id), payload)
                updated += 1
            else:
                create_spool(payload)
                created += 1
        except Exception as exc:  # noqa: BLE001 - collect row errors for user feedback
            errors.append(f"Row {index}: {exc}")

    return {"created": created, "updated": updated, "errors": errors}
