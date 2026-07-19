"""App and printer settings."""

from __future__ import annotations

import json
import os
from typing import Any

from db import connect, get_setting, row_to_dict, rows_to_dicts, set_setting


def get_settings() -> dict[str, Any]:
    with connect() as conn:
        printer = conn.execute(
            "SELECT id, name, model, serial, lan_ip, cloud_device_id, is_default FROM printers WHERE is_default = 1 LIMIT 1"
        ).fetchone()
        settings = {
            "default_low_stock_threshold_g": float(
                get_setting(conn, "default_low_stock_threshold_g", "100") or 100
            ),
            "material_low_stock_thresholds": json.loads(
                get_setting(conn, "material_low_stock_thresholds", "{}") or "{}"
            ),
            "drying_alert_days": int(get_setting(conn, "drying_alert_days", "30") or 30),
            "printer": row_to_dict(printer) if printer else None,
            "bambu_configured": bool(os.environ.get("BAMBU_LAN_ACCESS_CODE")),
            "bambu_cloud_configured": bool(
                os.environ.get("BAMBU_CLOUD_ACCESS_TOKEN")
                or (os.environ.get("BAMBU_CLOUD_EMAIL") and os.environ.get("BAMBU_CLOUD_PASSWORD"))
            ),
            "env": {
                "printer_ip": os.environ.get("BAMBU_PRINTER_IP", ""),
                "serial": os.environ.get("BAMBU_SERIAL", ""),
                "sync_cloud_interval_s": int(os.environ.get("SYNC_CLOUD_INTERVAL_S", "300")),
            },
        }
        sync_rows = conn.execute(
            "SELECT key, value, updated_at FROM sync_state ORDER BY key"
        ).fetchall()
        settings["sync_state"] = rows_to_dicts(sync_rows)
        return settings


def update_settings(data: dict[str, Any]) -> dict[str, Any]:
    with connect() as conn:
        if "default_low_stock_threshold_g" in data:
            set_setting(conn, "default_low_stock_threshold_g", str(data["default_low_stock_threshold_g"]))
        if "material_low_stock_thresholds" in data:
            set_setting(conn, "material_low_stock_thresholds", json.dumps(data["material_low_stock_thresholds"]))
        if "drying_alert_days" in data:
            set_setting(conn, "drying_alert_days", str(data["drying_alert_days"]))

        printer_data = data.get("printer")
        if printer_data:
            conn.execute(
                """
                UPDATE printers SET
                    name = COALESCE(?, name),
                    model = COALESCE(?, model),
                    serial = COALESCE(?, serial),
                    lan_ip = COALESCE(?, lan_ip),
                    cloud_device_id = COALESCE(?, cloud_device_id)
                WHERE is_default = 1
                """,
                (
                    printer_data.get("name"),
                    printer_data.get("model"),
                    printer_data.get("serial"),
                    printer_data.get("lan_ip"),
                    printer_data.get("cloud_device_id"),
                ),
            )
    return get_settings()
