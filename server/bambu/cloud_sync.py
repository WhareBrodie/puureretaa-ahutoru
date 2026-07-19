"""Bambu cloud API client for print task history."""

from __future__ import annotations

import logging
import os
from typing import Any

import requests

logger = logging.getLogger("bambu.cloud")

API_BASE = "https://api.bambulab.com"


class BambuCloudClient:
    def __init__(self) -> None:
        self._token: str | None = os.environ.get("BAMBU_CLOUD_ACCESS_TOKEN")
        self._session = requests.Session()

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

    def fetch_tasks(self, after: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        if not self.is_configured():
            return []
        params: dict[str, Any] = {"limit": limit}
        device_id = os.environ.get("BAMBU_CLOUD_DEVICE_ID")
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
