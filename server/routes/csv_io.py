"""CSV import and export."""

from __future__ import annotations

import csv
import io
import json
import re
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

SPOOLSTOCK_MARKERS = {"short_id", "filament.brand.name", "filament.material.name", "remaining_weight"}
HEX_IN_TEXT = re.compile(r"#[0-9A-Fa-f]{6}")


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


def detect_csv_format(fieldnames: list[str] | None) -> str:
    if not fieldnames:
        return "unknown"
    names = set(fieldnames)
    if SPOOLSTOCK_MARKERS.issubset(names):
        return "spoolstock"
    if "brand" in names and "material" in names:
        return "native"
    return "unknown"


def _parse_optional_float(value: str | None) -> float | None:
    if value is None or str(value).strip() == "":
        return None
    return float(value)


def _parse_optional_int(value: str | None) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    return int(float(value))


def _parse_date(value: str | None) -> str | None:
    if not value or not str(value).strip():
        return None
    text = str(value).strip()
    return text[:10] if "T" in text else text


def _parse_spoolstock_color(value: str | None) -> str | None:
    if not value or not str(value).strip():
        return None
    text = str(value).strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list) and parsed:
            first = str(parsed[0]).strip()
            return first if first.startswith("#") else f"#{first.lstrip('#')}"
    except json.JSONDecodeError:
        pass
    match = HEX_IN_TEXT.search(text)
    return match.group(0).upper() if match else None


def _combine_notes(*parts: str | None) -> str | None:
    chunks = [part.strip() for part in parts if part and part.strip()]
    if not chunks:
        return None
    return "\n\n".join(chunks)


def _is_truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes"}


def spoolstock_row_to_payload(row: dict[str, str]) -> dict[str, Any]:
    brand = (row.get("filament.brand.name") or "").strip()
    material = (row.get("filament.material.name") or "").strip()
    if not brand or not material:
        raise ValueError("filament.brand.name and filament.material.name are required")

    initial_weight = _parse_optional_float(row.get("size")) or 1000
    remaining = _parse_optional_float(row.get("remaining_weight"))
    if remaining is None:
        remaining = 0 if _is_truthy(row.get("depleted")) else initial_weight

    return {
        "brand": brand,
        "material": material.upper(),
        "color_name": (row.get("filament.name") or row.get("filament.color_family") or "").strip() or None,
        "color_hex": _parse_spoolstock_color(row.get("filament.color_hex_codes")),
        "purchase_price": _parse_optional_float(row.get("price")),
        "purchase_date": _parse_date(row.get("purchased_on")),
        "supplier": (row.get("purchase_source") or "").strip() or None,
        "batch_number": None,
        "rating": _parse_optional_int(row.get("filament.rating")),
        "remaining_g": remaining,
        "initial_weight_g": initial_weight,
        "empty_spool_weight_g": _parse_optional_float(row.get("empty_spool.weight")),
        "location_id": None,
        "notes": _combine_notes(row.get("notes"), row.get("filament.notes"), row.get("empty_spool.notes")),
        "low_stock_threshold_g": 100,
        "bambu_tag_uid": None,
        "qr_code_id": (row.get("short_id") or "").strip() or None,
    }


def native_row_to_payload(row: dict[str, str]) -> dict[str, Any]:
    return {
        "brand": row.get("brand", "").strip(),
        "material": row.get("material", "").strip(),
        "color_name": row.get("color_name") or None,
        "color_hex": row.get("color_hex") or None,
        "purchase_price": _parse_optional_float(row.get("purchase_price")),
        "purchase_date": row.get("purchase_date") or None,
        "supplier": row.get("supplier") or None,
        "batch_number": row.get("batch_number") or None,
        "rating": _parse_optional_int(row.get("rating")),
        "remaining_g": _parse_optional_float(row.get("remaining_g")),
        "initial_weight_g": _parse_optional_float(row.get("initial_weight_g")),
        "empty_spool_weight_g": _parse_optional_float(row.get("empty_spool_weight_g")),
        "location_id": int(row["location_id"]) if row.get("location_id") else None,
        "notes": row.get("notes") or None,
        "low_stock_threshold_g": _parse_optional_float(row.get("low_stock_threshold_g")),
        "bambu_tag_uid": row.get("bambu_tag_uid") or None,
        "qr_code_id": row.get("qr_code_id") or None,
    }


def import_spools_csv(
    csv_text: str,
    update_existing: bool = False,
    skip_depleted: bool = False,
) -> dict[str, Any]:
    reader = csv.DictReader(io.StringIO(csv_text))
    csv_format = detect_csv_format(reader.fieldnames)
    if csv_format == "unknown":
        raise ValueError(
            "Unrecognised CSV format. Expected native export columns or a SpoolStock export."
        )

    created = 0
    updated = 0
    skipped_depleted = 0
    errors: list[str] = []

    for index, row in enumerate(reader, start=2):
        try:
            if csv_format == "spoolstock" and skip_depleted and _is_truthy(row.get("depleted")):
                skipped_depleted += 1
                continue

            payload = (
                spoolstock_row_to_payload(row)
                if csv_format == "spoolstock"
                else native_row_to_payload(row)
            )
            if not payload["brand"] or not payload["material"]:
                raise ValueError("brand and material are required")

            spool_id = row.get("id")
            if update_existing and spool_id:
                update_spool(int(spool_id), payload)
                updated += 1
            else:
                create_spool(payload)
                created += 1
        except Exception as exc:  # noqa: BLE001 - collect row errors for user feedback
            label = row.get("short_id") or row.get("filament.name") or row.get("brand") or f"row {index}"
            errors.append(f"Row {index} ({label}): {exc}")

    return {
        "created": created,
        "updated": updated,
        "skipped_depleted": skipped_depleted,
        "format": csv_format,
        "errors": errors,
    }
