"""App and printer settings."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

from bambu.cloud_sync import BambuCloudClient
from bambu.mqtt_client import BambuMqttClient
from bambu.task_guard import (
    collect_auto_import_task_ids,
    ensure_cloud_sync_baseline,
    ignore_bambu_tasks,
    restore_auto_import_deductions,
)
from db import connect, get_setting, get_sync_state, row_to_dict, rows_to_dicts, set_setting, set_sync_state


def _cloud_credentials_configured() -> bool:
    return bool(
        os.environ.get("BAMBU_CLOUD_ACCESS_TOKEN")
        or (os.environ.get("BAMBU_CLOUD_EMAIL") and os.environ.get("BAMBU_CLOUD_PASSWORD"))
    )


def _mqtt_configured() -> bool:
    if _cloud_credentials_configured():
        return True
    cfg = BambuMqttClient.config()
    return bool(cfg["ip"] and cfg["serial"] and cfg["access_code"])


def _mqtt_mode() -> str | None:
    mode_env = os.environ.get("BAMBU_MQTT_MODE", "auto").lower()
    cfg = BambuMqttClient.config()
    cloud_ready = _cloud_credentials_configured()
    local_ready = bool(
        cfg["ip"]
        and (cfg["serial"] or os.environ.get("BAMBU_CLOUD_DEVICE_ID"))
        and (cfg["access_code"] or cloud_ready)
    )
    if mode_env == "local":
        return "local" if local_ready else None
    if mode_env == "cloud":
        return "cloud" if cloud_ready else None
    if local_ready:
        return "local"
    if cloud_ready:
        return "cloud"
    return None


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
            "bambu_cloud_configured": _cloud_credentials_configured(),
            "bambu_mqtt_configured": _mqtt_configured(),
            "bambu_mqtt_mode": _mqtt_mode(),
            "bambu_ftps_configured": bool(
                os.environ.get("BAMBU_PRINTER_IP")
                and (
                    os.environ.get("BAMBU_LAN_ACCESS_CODE")
                    or _cloud_credentials_configured()
                )
            ),
            # Back-compat for older UI checks
            "bambu_configured": _mqtt_configured(),
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
        settings["bambu_diagnostics"] = {
            "mqtt_last_message_at": get_sync_state(conn, "mqtt_last_message_at"),
            "mqtt_last_print_at": get_sync_state(conn, "mqtt_last_print_at"),
            "mqtt_last_ams_at": get_sync_state(conn, "mqtt_last_ams_at"),
            "mqtt_last_ams_slots": get_sync_state(conn, "mqtt_last_ams_slots"),
            "mqtt_last_pushall_at": get_sync_state(conn, "mqtt_last_pushall_at"),
            "mqtt_last_pushall_has_ams": get_sync_state(conn, "mqtt_last_pushall_has_ams"),
            "mqtt_last_pushall_tray_count": get_sync_state(conn, "mqtt_last_pushall_tray_count"),
            "live_ams_state": get_sync_state(conn, "live_ams_state"),
        }
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


def skip_cloud_history(delete_imported: bool = False) -> dict[str, Any]:
    """Stop backfilling Bambu cloud print history; optionally undo auto-import deductions."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    deleted = 0
    restored_spools = 0
    restored_grams = 0.0
    ignored_tasks = 0
    with connect() as conn:
        ensure_cloud_sync_baseline(conn)
        set_sync_state(conn, "cloud_tasks_after", now)

        if delete_imported:
            task_ids = collect_auto_import_task_ids(conn)
            restored_spools, restored_grams = restore_auto_import_deductions(conn)
            ignored_tasks += ignore_bambu_tasks(conn, task_ids, "cleared_import")

            conn.execute(
                """
                DELETE FROM print_usages
                WHERE print_job_id IN (
                    SELECT id FROM print_jobs WHERE source IN ('cloud', 'mqtt', 'ftps')
                )
                """
            )
            cur = conn.execute(
                "DELETE FROM print_jobs WHERE source IN ('cloud', 'mqtt', 'ftps')"
            )
            deleted = cur.rowcount

        client = BambuCloudClient()
        if client.is_configured():
            cloud_task_ids = [
                str(task.get("id") or task.get("taskId") or "")
                for task in client.fetch_tasks(limit=50)
            ]
            ignored_tasks += ignore_bambu_tasks(conn, cloud_task_ids, "skip_cloud_history")

    result = get_settings()
    result["cloud_sync_baseline"] = now
    result["deleted_imported_prints"] = deleted
    result["restored_spools"] = restored_spools
    result["restored_grams"] = restored_grams
    result["ignored_tasks"] = ignored_tasks
    return result
