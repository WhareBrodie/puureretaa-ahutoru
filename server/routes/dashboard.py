"""Dashboard summaries, stats, and alerts."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from db import connect, get_setting, rows_to_dicts
from routes.ams import get_live_printer_state
from routes.prints import list_prints
from routes.spools import list_spools


def _filament_stock_groups() -> list[dict[str, Any]]:
    """Group spools by brand+material+color and sum remaining weight (includes depleted-only filaments)."""
    spools = list_spools()
    with connect() as conn:
        default_threshold = float(get_setting(conn, "default_low_stock_threshold_g", "100") or 100)

    groups: dict[str, dict[str, Any]] = {}
    for spool in spools:
        key = f"{spool['brand']}|{spool['material']}|{spool.get('color_name') or ''}"
        remaining = spool.get("remaining_g") or 0
        if key not in groups:
            groups[key] = {
                "brand": spool["brand"],
                "material": spool["material"],
                "color_name": spool.get("color_name"),
                "color_hex": spool.get("color_hex"),
                "total_remaining_g": 0.0,
                "spool_count": 0,
                "active_spool_count": 0,
                "threshold_g": spool.get("low_stock_threshold_g") or default_threshold,
            }
        group = groups[key]
        group["total_remaining_g"] += remaining
        group["spool_count"] += 1
        if remaining > 0:
            group["active_spool_count"] += 1
        if spool.get("color_hex") and not group.get("color_hex"):
            group["color_hex"] = spool["color_hex"]

    for group in groups.values():
        group["no_stock"] = group["active_spool_count"] == 0 and group["spool_count"] > 0

    return list(groups.values())


def _days_since(iso_ts: str | None) -> int | None:
    if not iso_ts:
        return None
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - dt).days
    except ValueError:
        return None


def get_low_stock_alerts() -> list[dict[str, Any]]:
    alerts = []
    for group in _filament_stock_groups():
        if group["total_remaining_g"] <= group["threshold_g"]:
            alerts.append(
                {
                    "type": "filament_low",
                    "brand": group["brand"],
                    "material": group["material"],
                    "color_name": group["color_name"],
                    "color_hex": group.get("color_hex"),
                    "total_remaining_g": group["total_remaining_g"],
                    "threshold_g": group["threshold_g"],
                    "spool_count": group["spool_count"],
                    "no_stock": group["no_stock"],
                }
            )
    with connect() as conn:
        material_thresholds = json.loads(get_setting(conn, "material_low_stock_thresholds", "{}") or "{}")
        totals = conn.execute(
            """
            SELECT material, SUM(COALESCE(remaining_g, 0)) AS total_g
            FROM spools GROUP BY material
            """
        ).fetchall()
        for row in totals:
            threshold = material_thresholds.get(row["material"])
            if threshold is not None and row["total_g"] <= float(threshold):
                alerts.append(
                    {
                        "type": "material_low",
                        "material": row["material"],
                        "total_g": row["total_g"],
                        "threshold_g": threshold,
                    }
                )
    return alerts


def get_drying_alerts(days_threshold: int = 30) -> list[dict[str, Any]]:
    alerts = []
    for spool in list_spools():
        days = _days_since(spool.get("last_dried_at"))
        if days is None or days >= days_threshold:
            alerts.append(
                {
                    "type": "needs_drying",
                    "spool_id": spool["id"],
                    "brand": spool["brand"],
                    "material": spool["material"],
                    "color_name": spool["color_name"],
                    "days_since_dried": days,
                }
            )
    return alerts


def get_dashboard() -> dict[str, Any]:
    spools = list_spools()
    pending = list_prints(pending_review_only=True)
    live = get_live_printer_state()
    return {
        "spool_count": len(spools),
        "total_remaining_g": sum(s.get("remaining_g") or 0 for s in spools),
        "pending_reviews": len(pending),
        "low_stock_alerts": get_low_stock_alerts(),
        "drying_alerts": get_drying_alerts()[:10],
        "live_printer": live.get("printer"),
        "live_ams": live.get("ams"),
        "recent_prints": list_prints()[:5],
    }


def get_stats() -> dict[str, Any]:
    with connect() as conn:
        material_usage = conn.execute(
            """
            SELECT COALESCE(pu.material, s.material, 'Unknown') AS material,
                   SUM(pu.used_g) AS total_g,
                   COUNT(DISTINCT pu.print_job_id) AS print_count
            FROM print_usages pu
            LEFT JOIN spools s ON s.id = pu.spool_id
            GROUP BY COALESCE(pu.material, s.material, 'Unknown')
            ORDER BY total_g DESC
            """
        ).fetchall()
        color_usage = conn.execute(
            """
            SELECT s.color_name, s.color_hex, s.material, SUM(pu.used_g) AS total_g
            FROM print_usages pu
            JOIN spools s ON s.id = pu.spool_id
            GROUP BY s.id
            ORDER BY total_g DESC
            LIMIT 10
            """
        ).fetchall()
        monthly = conn.execute(
            """
            SELECT strftime('%Y-%m', COALESCE(started_at, created_at)) AS month,
                   SUM(total_used_g) AS total_g,
                   COUNT(*) AS prints
            FROM print_jobs
            GROUP BY month
            ORDER BY month DESC
            LIMIT 12
            """
        ).fetchall()
        brand_totals = conn.execute(
            """
            SELECT s.brand, SUM(pu.used_g) AS total_g
            FROM print_usages pu
            JOIN spools s ON s.id = pu.spool_id
            GROUP BY s.brand
            ORDER BY total_g DESC
            """
        ).fetchall()
    return {
        "material_usage": rows_to_dicts(material_usage),
        "top_colors": rows_to_dicts(color_usage),
        "monthly_usage": rows_to_dicts(monthly),
        "brand_usage": rows_to_dicts(brand_totals),
    }


def get_reorder_suggestions() -> list[dict[str, Any]]:
    """Low-stock filaments worth reordering (deduped by brand/material/color)."""
    suggestions = []
    for group in _filament_stock_groups():
        if group["total_remaining_g"] <= group["threshold_g"]:
            suggestions.append(
                {
                    "brand": group["brand"],
                    "material": group["material"],
                    "color_name": group["color_name"],
                    "color_hex": group.get("color_hex"),
                    "total_remaining_g": group["total_remaining_g"],
                    "threshold_g": group["threshold_g"],
                    "spool_count": group["spool_count"],
                    "no_stock": group["no_stock"],
                }
            )
    return sorted(
        suggestions,
        key=lambda item: (
            item["total_remaining_g"],
            item["brand"],
            item["material"],
            item.get("color_name") or "",
        ),
    )
