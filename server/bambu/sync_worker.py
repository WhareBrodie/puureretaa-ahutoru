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

from bambu.cloud_sync import BambuCloudClient
from bambu.ftps_gcode import BambuFtpsClient, parse_filament_usage
from bambu.mqtt_client import BambuMqttClient
from bambu.print_processor import process_print_job, store_live_state
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
            gcode = self.ftps.resolve_gcode_content(event["gcode_file"])
            if gcode:
                usages = parse_filament_usage(gcode, float(event.get("completion_percent") or 100))
                source = "ftps"

        if not usages:
            logger.info("No filament usage data yet for %s; cloud poll will retry", event.get("gcode_file"))
            return

        if bambu_task_id:
            with connect() as conn:
                existing = conn.execute(
                    "SELECT id FROM print_jobs WHERE bambu_task_id = ?", (bambu_task_id,)
                ).fetchone()
            if existing:
                return

        process_print_job(
            title=event.get("subtask_name") or event.get("gcode_file"),
            started_at=None,
            ended_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            duration_s=None,
            status=event.get("status") or "completed",
            source=source,
            bambu_task_id=bambu_task_id,
            gcode_file=event.get("gcode_file"),
            completion_percent=float(event.get("completion_percent") or 100),
            usages=usages,
        )

    def _find_matching_cloud_task(self, event: dict) -> dict | None:
        tasks = self.cloud.fetch_tasks(limit=5)
        filename = (event.get("gcode_file") or "").lower()
        for task in tasks:
            title = (task.get("title") or "").lower()
            task_id = str(task.get("id") or task.get("taskId") or "")
            if filename and filename in title:
                detail = self.cloud.fetch_task_detail(task_id)
                return detail or task
        return tasks[0] if tasks else None

    def poll_cloud_tasks(self) -> None:
        if not self.cloud.is_configured():
            return
        with connect() as conn:
            after = get_sync_state(conn, "cloud_tasks_after")
        tasks = self.cloud.fetch_tasks(after=after, limit=20)
        if not tasks:
            return

        for task in reversed(tasks):
            task_id = str(task.get("id") or task.get("taskId") or "")
            if not task_id:
                continue
            with connect() as conn:
                existing = conn.execute(
                    "SELECT id FROM print_jobs WHERE bambu_task_id = ?", (task_id,)
                ).fetchone()
            if existing:
                continue
            detail = self.cloud.fetch_task_detail(task_id) or task
            usages = self.cloud.extract_filament_usages(detail)
            if not usages:
                continue
            process_print_job(
                title=detail.get("title") or "Cloud print",
                started_at=detail.get("startTime"),
                ended_at=detail.get("endTime"),
                duration_s=detail.get("costTime"),
                status="completed",
                source="cloud",
                bambu_task_id=task_id,
                gcode_file=None,
                completion_percent=100,
                usages=usages,
            )

        newest = tasks[0]
        cursor = newest.get("endTime") or newest.get("startTime")
        if cursor:
            with connect() as conn:
                set_sync_state(conn, "cloud_tasks_after", cursor)

    def run(self) -> None:
        init_db()
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
