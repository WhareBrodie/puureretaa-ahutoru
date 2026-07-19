"""Background Bambu sync worker (cloud API + cloud/local MQTT + optional FTPS)."""

from __future__ import annotations

import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from bambu.cloud_sync import (
    BambuCloudClient,
    normalize_cloud_task_status,
    task_completion_percent,
    task_is_importable,
)
from bambu.ftps_gcode import BambuFtpsClient, parse_filament_usage
from bambu.mqtt_client import BambuMqttClient
from bambu.print_processor import process_print_job, store_live_state
from bambu.task_guard import ensure_cloud_sync_baseline, is_before_baseline, is_bambu_task_ignored, task_timestamp
from db import connect, get_sync_state, init_db, set_sync_state

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("bambu.sync_worker")


class SyncWorker:
    def __init__(self) -> None:
        self.cloud = BambuCloudClient()
        self.mqtt = BambuMqttClient(
            cloud_client=self.cloud,
            on_print_complete=self.on_print_complete,
            on_state_update=self.on_state_update,
        )
        self.ftps = BambuFtpsClient(cloud_client=self.cloud)
        self.cloud_interval = int(os.environ.get("SYNC_CLOUD_INTERVAL_S", "300"))

    def on_state_update(self, printer_state: dict, trays: dict) -> None:
        store_live_state(printer_state, trays)

    def on_print_complete(self, event: dict) -> None:
        logger.info("Print complete event: %s", event.get("gcode_file"))
        if not self.cloud.is_configured():
            logger.warning("Print finished on MQTT but cloud credentials are not configured; skipping auto-import")
            return

        usages: list[dict] = []
        source = "mqtt"
        task = self._find_matching_cloud_task(event)
        if task:
            usages = self.cloud.extract_filament_usages(task)
            source = "cloud"
            bambu_task_id = str(task.get("id") or task.get("taskId") or "")
        else:
            bambu_task_id = None

        if not usages and event.get("gcode_file") and self.ftps.is_configured():
            event_status = event.get("status") or "completed"
            default_completion = 100.0 if event_status == "completed" else float(event.get("completion_percent") or 0)
            gcode = self.ftps.resolve_gcode_content(event["gcode_file"])
            if gcode:
                usages = parse_filament_usage(gcode, default_completion)
                source = "ftps"

        event_status = event.get("status") or "completed"
        if event_status == "cancelled":
            logger.info("Skipping cancelled MQTT print %s", event.get("gcode_file"))
            return

        if not usages:
            logger.info("No filament usage data yet for %s; cloud poll will retry", event.get("gcode_file"))
            return

        if bambu_task_id:
            with connect() as conn:
                if is_bambu_task_ignored(conn, bambu_task_id):
                    return
                existing = conn.execute(
                    "SELECT id FROM print_jobs WHERE bambu_task_id = ?", (bambu_task_id,)
                ).fetchone()
            if existing:
                return

        completion = float(event.get("completion_percent") if event.get("completion_percent") is not None else 100)
        if event_status == "failed":
            completion = float(event.get("completion_percent") or 0)

        result = process_print_job(
            title=event.get("subtask_name") or event.get("gcode_file"),
            started_at=None,
            ended_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            duration_s=None,
            status=event_status,
            source=source,
            bambu_task_id=bambu_task_id,
            gcode_file=event.get("gcode_file"),
            completion_percent=completion,
            usages=usages,
        )
        if result.get("ignored"):
            logger.info("Skipped MQTT print import for task %s", bambu_task_id or event.get("gcode_file"))

    def _find_matching_cloud_task(self, event: dict) -> dict | None:
        tasks = self.cloud.fetch_tasks(limit=10)
        filename = (event.get("gcode_file") or "").lower()
        for task in tasks:
            if not task_is_importable(task):
                continue
            title = (task.get("title") or "").lower()
            task_id = str(task.get("id") or task.get("taskId") or "")
            if filename and filename in title:
                detail = self.cloud.fetch_task_detail(task_id) or task
                if task_is_importable(detail):
                    return detail
        return None

    def poll_cloud_tasks(self) -> None:
        if not self.cloud.is_configured():
            return
        with connect() as conn:
            ensure_cloud_sync_baseline(conn)
        # Fetch recent tasks without the `after` cursor — Bambu expects a task id there,
        # and we previously stored ISO timestamps which skipped finished jobs.
        tasks = self.cloud.fetch_tasks(limit=50)
        if not tasks:
            return

        for task in reversed(tasks):
            task_id = str(task.get("id") or task.get("taskId") or "")
            if not task_id:
                continue
            detail = self.cloud.fetch_task_detail(task_id) or task
            if not task_is_importable(detail):
                continue
            normalized_status = normalize_cloud_task_status(detail)
            if not normalized_status:
                continue
            if normalized_status == "cancelled":
                logger.info("Skipping cancelled cloud task %s", task_id)
                continue
            with connect() as conn:
                if is_bambu_task_ignored(conn, task_id):
                    continue
                existing = conn.execute(
                    "SELECT id FROM print_jobs WHERE bambu_task_id = ?", (task_id,)
                ).fetchone()
            if existing:
                continue
            ended_at = task_timestamp(detail) or task_timestamp(task)
            with connect() as conn:
                if is_before_baseline(conn, ended_at):
                    continue
            usages = self.cloud.extract_filament_usages(detail)
            if not usages:
                continue
            completion = task_completion_percent(detail, normalized_status)
            result = process_print_job(
                title=detail.get("title") or "Cloud print",
                started_at=detail.get("startTime"),
                ended_at=detail.get("endTime"),
                duration_s=detail.get("costTime"),
                status=normalized_status,
                source="cloud",
                bambu_task_id=task_id,
                gcode_file=None,
                completion_percent=completion,
                usages=usages,
            )
            if result.get("ignored"):
                logger.info("Skipped cloud task %s (ignored or before baseline)", task_id)

        newest = tasks[0]
        task_id = str(newest.get("id") or newest.get("taskId") or "")
        if task_id:
            with connect() as conn:
                set_sync_state(conn, "cloud_tasks_after", task_id)

    def run(self) -> None:
        init_db()
        if self.cloud.is_configured():
            with connect() as conn:
                baseline = ensure_cloud_sync_baseline(conn)
            logger.info("Cloud sync baseline: %s", baseline)
        mode = self.mqtt.connection_mode()
        if self.cloud.is_configured():
            serial = self.cloud.resolve_serial()
            logger.info(
                "Bambu cloud configured; serial=%s mqtt_mode=%s cloud_poll=%ss",
                serial or "(unknown)",
                mode or "none",
                self.cloud_interval,
            )
        self.mqtt.start()
        logger.info("Sync worker started")
        while True:
            try:
                self.poll_cloud_tasks()
            except Exception:
                logger.exception("Cloud poll failed")
            time.sleep(self.cloud_interval)


if __name__ == "__main__":
    SyncWorker().run()
