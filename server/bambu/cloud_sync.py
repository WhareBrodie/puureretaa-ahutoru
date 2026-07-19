"""Bambu cloud API client for print task history and device discovery."""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any

import requests

from db import ceil_usage_g

logger = logging.getLogger("bambu.cloud")

# Bambu Studio TaskState enum (numeric status on /my/tasks hits).
TASK_STATUS_PRINT_SUCCESS = 6
TASK_STATUS_PRINT_FAILED = 7
TASK_STATUS_SEND_CANCELED = 3
TASK_STATUS_SEND_FAILED = 4
TASK_STATUS_SEND_COMPLETED = 2
TASK_STATUS_PRINTING = 5


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
        if raw in (TASK_STATUS_PRINTING,):
            return None
        if raw == TASK_STATUS_PRINT_SUCCESS:
            return "completed"
        if raw == TASK_STATUS_PRINT_FAILED:
            return "failed"
        if raw in (TASK_STATUS_SEND_CANCELED, TASK_STATUS_SEND_FAILED):
            return "cancelled"
        if raw == TASK_STATUS_SEND_COMPLETED:
            return None if task_is_still_printing(task) else "completed"
        return None
    token = str(raw).strip().lower()
    if token in {"5", "printing"}:
        return None
    if token in {"6", "completed", "success", "print_success"}:
        return "completed"
    if token in {"7", "failed", "print_failed"}:
        return "failed"
    if token in {"3", "4", "cancelled", "canceled", "send_canceled", "send_failed"}:
        return "cancelled"
    if token in {"2", "send_completed"}:
        return None if task_is_still_printing(task) else "completed"
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

    def fetch_task_for_deduction(self, task_id: str) -> dict[str, Any] | None:
        detail = self.fetch_task_detail(task_id)
        if detail:
            return detail
        for task in self.fetch_tasks(limit=50):
            candidate = str(task.get("id") or task.get("taskId") or "")
            if candidate == str(task_id):
                return task
        return None

    def _find_nested_ams_mapping(self, obj: Any, depth: int = 0) -> list[int] | None:
        if depth > 10:
            return None
        if isinstance(obj, dict):
            for key in ("ams_mapping", "amsMapping"):
                raw = obj.get(key)
                if isinstance(raw, list) and raw and not isinstance(raw[0], dict):
                    try:
                        return [int(value) for value in raw]
                    except (TypeError, ValueError):
                        continue
            for value in obj.values():
                found = self._find_nested_ams_mapping(value, depth + 1)
                if found:
                    return found
        elif isinstance(obj, list):
            for item in obj:
                found = self._find_nested_ams_mapping(item, depth + 1)
                if found:
                    return found
        return None

    def extract_ams_mapping(self, task: dict[str, Any]) -> list[int] | None:
        profile = task.get("profile") or task
        for key in ("ams_mapping", "amsMapping", "ams_detail_mapping", "amsDetailMapping"):
            raw = profile.get(key) or task.get(key)
            if not isinstance(raw, list) or not raw:
                continue
            if isinstance(raw[0], dict):
                continue
            try:
                return [int(value) for value in raw]
            except (TypeError, ValueError):
                continue
        return self._find_nested_ams_mapping(task)

    def _usages_from_ams_detail_mapping(self, task: dict[str, Any]) -> list[dict[str, Any]] | None:
        profile = task.get("profile") or task
        for key in ("amsDetailMapping", "ams_detail_mapping"):
            raw = profile.get(key) or task.get(key)
            if not isinstance(raw, list) or not raw or not isinstance(raw[0], dict):
                continue
            usages: list[dict[str, Any]] = []
            for entry in raw:
                used_g = ceil_usage_g(
                    float(
                        entry.get("usedG")
                        or entry.get("used_g")
                        or entry.get("weight")
                        or 0
                    )
                )
                if used_g <= 0:
                    continue
                slot_raw = (
                    entry.get("slotId")
                    if entry.get("slotId") is not None
                    else entry.get("slot_id")
                    if entry.get("slot_id") is not None
                    else entry.get("trayId")
                    if entry.get("trayId") is not None
                    else entry.get("tray_id")
                )
                if slot_raw is None:
                    continue
                tray_index = int(slot_raw)
                if tray_index >= 254:
                    ams_slot = 1
                else:
                    ams_slot = max(1, min(4, tray_index + 1))
                color = entry.get("color") or entry.get("filamentColor") or ""
                if color and not str(color).startswith("#"):
                    color = f"#{str(color)[:6]}"
                usages.append(
                    {
                        "ams_slot": ams_slot,
                        "material": (entry.get("type") or entry.get("filamentType") or "UNKNOWN").upper(),
                        "color": color or None,
                        "used_g": used_g,
                        "used_m": float(entry.get("usedM") or entry.get("used_m") or 0) or None,
                    }
                )
            if usages:
                return usages
        return None

    def map_slicer_filament_to_ams_slot(
        self,
        filament_id: int,
        ams_mapping: list[int] | None,
    ) -> int:
        if ams_mapping:
            slicer_index = max(0, int(filament_id) - 1)
            if slicer_index < len(ams_mapping):
                tray_index = int(ams_mapping[slicer_index])
                if tray_index >= 254:
                    return 1
                return max(1, min(4, tray_index + 1))
        return max(1, min(4, int(filament_id)))

    def extract_filament_usages(self, task: dict[str, Any]) -> list[dict[str, Any]]:
        detail_usages = self._usages_from_ams_detail_mapping(task)
        if detail_usages:
            return detail_usages

        usages: list[dict[str, Any]] = []
        profile = task.get("profile") or task
        plates = profile.get("plates") or task.get("plates") or []
        ams_mapping = self.extract_ams_mapping(task)
        for plate in plates:
            for filament in plate.get("filaments") or []:
                color = filament.get("color") or ""
                if color and not color.startswith("#"):
                    color = f"#{color[:6]}"
                filament_id = int(filament.get("id") or len(usages) + 1)
                usages.append(
                    {
                        "ams_slot": self.map_slicer_filament_to_ams_slot(filament_id, ams_mapping),
                        "material": (filament.get("type") or "UNKNOWN").upper(),
                        "color": color,
                        "used_g": ceil_usage_g(float(filament.get("used_g") or 0)),
                        "used_m": float(filament.get("used_m") or 0) if filament.get("used_m") else None,
                    }
                )
        if not usages and task.get("weight"):
            usages.append(
                {
                    "ams_slot": 1,
                    "material": "UNKNOWN",
                    "color": None,
                    "used_g": ceil_usage_g(float(task.get("weight") or 0)),
                    "used_m": None,
                }
            )
        return usages
