"""Bambu cloud API client for print task history and device discovery."""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any

import requests

logger = logging.getLogger("bambu.cloud")

# Bambu Studio TaskState enum (numeric status on /my/tasks hits).
TASK_STATUS_PRINT_SUCCESS = 6
TASK_STATUS_PRINT_FAILED = 7
TASK_STATUS_SEND_CANCELED = 3
TASK_STATUS_SEND_FAILED = 4


def _parse_iso8601(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def task_is_still_printing(task: dict[str, Any]) -> bool:
    """OpenBambuAPI: endTime within ~1 minute of startTime means actively printing."""
    start = _parse_iso8601(task.get("startTime") or task.get("start_time"))
    end = _parse_iso8601(task.get("endTime") or task.get("end_time"))
    if not start or not end:
        return False
    return (end - start).total_seconds() < 90


def normalize_cloud_task_status(task: dict[str, Any]) -> str | None:
    """Return completed/failed/cancelled, or None if the task is not finished yet."""
    raw = task.get("status")
    if raw is None:
        return None
    if isinstance(raw, int):
        if raw == TASK_STATUS_PRINT_SUCCESS:
            return "completed"
        if raw == TASK_STATUS_PRINT_FAILED:
            return "failed"
        if raw in (TASK_STATUS_SEND_CANCELED, TASK_STATUS_SEND_FAILED):
            return "cancelled"
        return None
    token = str(raw).strip().lower()
    if token in {"6", "completed", "success", "print_success"}:
        return "completed"
    if token in {"7", "failed", "print_failed"}:
        return "failed"
    if token in {"3", "4", "cancelled", "canceled", "send_canceled", "send_failed"}:
        return "cancelled"
    return None


def task_is_importable(task: dict[str, Any]) -> bool:
    status = normalize_cloud_task_status(task)
    if status is None:
        return False
    if task_is_still_printing(task):
        return False
    return True


def task_completion_percent(task: dict[str, Any], normalized_status: str) -> float:
    if normalized_status == "completed":
        return 100.0
    if normalized_status == "cancelled":
        return 0.0
    for key in ("progress", "mc_percent", "completion_percent", "mcPercent"):
        value = task.get(key)
        if value is not None:
            try:
                return max(0.0, min(float(value), 100.0))
            except (TypeError, ValueError):
                continue
    return 0.0

API_BASE = "https://api.bambulab.com"
DEFAULT_MQTT_BROKER = "us.mqtt.bambulab.com"


class BambuCloudClient:
    def __init__(self) -> None:
        self._token: str | None = os.environ.get("BAMBU_CLOUD_ACCESS_TOKEN")
        self._session = requests.Session()
        self._user_id: int | None = None
        self._devices: list[dict[str, Any]] | None = None

    def is_configured(self) -> bool:
        return bool(
            self._token
            or (os.environ.get("BAMBU_CLOUD_EMAIL") and os.environ.get("BAMBU_CLOUD_PASSWORD"))
        )

    def _ensure_token(self) -> str | None:
        if self._token:
            return self._token
        email = os.environ.get("BAMBU_CLOUD_EMAIL")
        password = os.environ.get("BAMBU_CLOUD_PASSWORD")
        if not email or not password:
            return None
        try:
            resp = self._session.post(
                f"{API_BASE}/v1/user-service/user/login",
                json={"account": email, "password": password},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("loginType") == "verifyCode":
                logger.error(
                    "Bambu cloud login requires 2FA verification; set BAMBU_CLOUD_ACCESS_TOKEN in Portainer instead"
                )
                return None
            self._token = data.get("accessToken") or data.get("access_token")
            return self._token
        except Exception:
            logger.exception("Bambu cloud login failed")
            return None

    def _headers(self) -> dict[str, str]:
        token = self._ensure_token()
        if not token:
            return {}
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    def get_user_id(self) -> int | None:
        if self._user_id is not None:
            return self._user_id
        if not self.is_configured():
            return None
        try:
            resp = self._session.get(
                f"{API_BASE}/v1/design-user-service/my/preference",
                headers=self._headers(),
                timeout=30,
            )
            if resp.status_code == 401:
                self._token = None
                resp = self._session.get(
                    f"{API_BASE}/v1/design-user-service/my/preference",
                    headers=self._headers(),
                    timeout=30,
                )
            resp.raise_for_status()
            uid = resp.json().get("uid")
            if isinstance(uid, int):
                self._user_id = uid
            return self._user_id
        except Exception:
            logger.exception("Failed to fetch Bambu user id")
            return None

    def get_mqtt_broker(self) -> str:
        return os.environ.get("BAMBU_MQTT_BROKER", DEFAULT_MQTT_BROKER).strip() or DEFAULT_MQTT_BROKER

    def fetch_bound_devices(self, force: bool = False) -> list[dict[str, Any]]:
        if self._devices is not None and not force:
            return self._devices
        if not self.is_configured():
            return []
        try:
            resp = self._session.get(
                f"{API_BASE}/v1/iot-service/api/user/bind",
                headers=self._headers(),
                timeout=30,
            )
            if resp.status_code == 401:
                self._token = None
                resp = self._session.get(
                    f"{API_BASE}/v1/iot-service/api/user/bind",
                    headers=self._headers(),
                    timeout=30,
                )
            resp.raise_for_status()
            data = resp.json()
            devices = data.get("devices") or []
            self._devices = devices if isinstance(devices, list) else []
            return self._devices
        except Exception:
            logger.exception("Failed to fetch bound Bambu devices")
            return []

    def resolve_device(self) -> dict[str, Any] | None:
        serial = os.environ.get("BAMBU_SERIAL", "").strip()
        device_id = os.environ.get("BAMBU_CLOUD_DEVICE_ID", "").strip()
        devices = self.fetch_bound_devices()
        if not devices:
            return None
        if device_id:
            for device in devices:
                if str(device.get("dev_id") or "") == device_id:
                    return device
        if serial:
            for device in devices:
                if str(device.get("dev_id") or "") == serial:
                    return device
        if len(devices) == 1:
            return devices[0]
        return None

    def resolve_serial(self) -> str:
        serial = os.environ.get("BAMBU_SERIAL", "").strip()
        if serial:
            return serial
        device = self.resolve_device()
        return str(device.get("dev_id") or "").strip() if device else ""

    def resolve_access_code(self) -> str:
        code = os.environ.get("BAMBU_LAN_ACCESS_CODE", "").strip()
        if code:
            return code
        device = self.resolve_device()
        if not device:
            return ""
        return str(device.get("dev_access_code") or "").strip()

    def fetch_tasks(self, after: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        if not self.is_configured():
            return []
        params: dict[str, Any] = {"limit": limit}
        device_id = os.environ.get("BAMBU_CLOUD_DEVICE_ID") or os.environ.get("BAMBU_SERIAL")
        if device_id:
            params["deviceId"] = device_id
        if after:
            params["after"] = after
        try:
            resp = self._session.get(
                f"{API_BASE}/v1/user-service/my/tasks",
                headers=self._headers(),
                params=params,
                timeout=30,
            )
            if resp.status_code == 401:
                self._token = None
                resp = self._session.get(
                    f"{API_BASE}/v1/user-service/my/tasks",
                    headers=self._headers(),
                    params=params,
                    timeout=30,
                )
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, dict):
                return data.get("hits") or data.get("tasks") or data.get("data") or []
            if isinstance(data, list):
                return data
            return []
        except Exception:
            logger.exception("Failed to fetch Bambu cloud tasks")
            return []

    def fetch_task_detail(self, task_id: str) -> dict[str, Any] | None:
        if not self.is_configured() or not task_id:
            return None
        try:
            resp = self._session.get(
                f"{API_BASE}/v1/user-service/my/task/{task_id}",
                headers=self._headers(),
                timeout=30,
            )
            if resp.status_code in {403, 404}:
                return None
            resp.raise_for_status()
            return resp.json()
        except Exception:
            logger.exception("Failed to fetch task detail %s", task_id)
            return None

    def extract_filament_usages(self, task: dict[str, Any]) -> list[dict[str, Any]]:
        usages: list[dict[str, Any]] = []
        profile = task.get("profile") or task
        plates = profile.get("plates") or task.get("plates") or []
        for plate in plates:
            for filament in plate.get("filaments") or []:
                color = filament.get("color") or ""
                if color and not color.startswith("#"):
                    color = f"#{color[:6]}"
                usages.append(
                    {
                        "ams_slot": int(filament.get("id") or len(usages) + 1),
                        "material": (filament.get("type") or "UNKNOWN").upper(),
                        "color": color,
                        "used_g": float(filament.get("used_g") or 0),
                        "used_m": float(filament.get("used_m") or 0) if filament.get("used_m") else None,
                    }
                )
        if not usages and task.get("weight"):
            usages.append(
                {
                    "ams_slot": 1,
                    "material": "UNKNOWN",
                    "color": None,
                    "used_g": float(task.get("weight") or 0),
                    "used_m": None,
                }
            )
        return usages
