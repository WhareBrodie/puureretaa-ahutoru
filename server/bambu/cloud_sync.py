"""Bambu cloud API client for print task history and device discovery."""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any

import requests

from bambu.credentials import (
    cloud_credentials_configured,
    cloud_refresh_token_from_db,
    record_cloud_auth_error,
    record_cloud_auth_ok,
    resolve_cloud_access_token,
    save_cloud_access_token,
)
from db import ceil_usage_g

logger = logging.getLogger("bambu.cloud")


class CloudAuthError(RuntimeError):
    """Bambu rejected cloud credentials (expired/revoked token or failed login)."""

# Cloud GET /v1/user-service/my/tasks hit `status` values (Bambu Studio parse_task_status
# + OpenBambuAPI field notes). These are NOT the Studio TaskState send/print stage enums
# (those use 3=send_canceled, 4=send_failed, 5=printing, 6=print_success, 7=print_failed).
CLOUD_TASK_PRINTING = {1, 4, 5}
CLOUD_TASK_FINISHED = {2, 6}  # 2 is what /my/tasks returns; 6 kept as legacy alias
CLOUD_TASK_FAILED = {3, 7}  # 3 = aborted or failed on /my/tasks; 7 = legacy print_failed


def _parse_iso8601(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def task_duration_seconds(task: dict[str, Any]) -> float | None:
    start = _parse_iso8601(task.get("startTime") or task.get("start_time"))
    end = _parse_iso8601(task.get("endTime") or task.get("end_time"))
    if not start or not end:
        return None
    return max(0.0, (end - start).total_seconds())


def task_is_still_printing(task: dict[str, Any]) -> bool:
    """OpenBambuAPI: endTime within ~1 minute of startTime means actively printing."""
    duration = task_duration_seconds(task)
    if duration is None:
        return False
    return duration < 60


def normalize_cloud_task_status(task: dict[str, Any]) -> str | None:
    """Return completed/failed/cancelled, or None if the task is not finished yet."""
    raw = task.get("status")
    if raw is None:
        return None
    if isinstance(raw, int):
        if raw in CLOUD_TASK_PRINTING:
            return None
        if raw in CLOUD_TASK_FINISHED:
            return None if task_is_still_printing(task) else "completed"
        if raw in CLOUD_TASK_FAILED:
            # Early abort (end≈start) is treated as still-open / ignore via importable().
            return None if task_is_still_printing(task) else "failed"
        return None
    token = str(raw).strip().lower()
    if token in {"1", "4", "5", "printing"}:
        return None
    if token in {"2", "6", "completed", "success", "print_success", "send_completed"}:
        return None if task_is_still_printing(task) else "completed"
    if token in {"3", "7", "failed", "print_failed", "aborted"}:
        return None if task_is_still_printing(task) else "failed"
    if token in {"cancelled", "canceled", "send_canceled", "send_failed"}:
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
    # Cloud aborted/failed tasks often omit progress; weight/length stay at the full
    # slice estimate. Scale by elapsed/costTime so we don't deduct a full spool for a
    # mid-print cancel.
    if normalized_status == "failed":
        duration = task_duration_seconds(task)
        try:
            cost = float(task.get("costTime") or 0)
        except (TypeError, ValueError):
            cost = 0.0
        if duration and cost > 0:
            return max(0.0, min((duration / cost) * 100.0, 100.0))
    return 0.0

API_BASE = "https://api.bambulab.com"
DEFAULT_MQTT_BROKER = "us.mqtt.bambulab.com"


class BambuCloudClient:
    def __init__(self) -> None:
        self._session_token: str | None = None
        self._session = requests.Session()
        self._user_id: int | None = None
        self._devices: list[dict[str, Any]] | None = None
        self._refresh_attempted = False
        self._password_relogin_attempted = False

    def is_configured(self) -> bool:
        return cloud_credentials_configured()

    def _persist_login_tokens(self, data: dict[str, Any]) -> str | None:
        access = data.get("accessToken") or data.get("access_token")
        if not access:
            return None
        refresh = data.get("refreshToken") or data.get("refresh_token")
        save_cloud_access_token(
            access,
            refresh_token=refresh,
            expires_in=data.get("expiresIn") or data.get("expires_in"),
        )
        self._session_token = access
        record_cloud_auth_ok()
        return access

    def login(
        self,
        email: str,
        password: str,
        *,
        code: str | None = None,
    ) -> dict[str, Any]:
        """Login with email/password, optionally a verification code. Persists tokens on success."""
        payload: dict[str, Any] = {"account": email.strip(), "password": password}
        if code:
            payload["code"] = code.strip()
        resp = self._session.post(
            f"{API_BASE}/v1/user-service/user/login",
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json() if resp.content else {}
        if data.get("loginType") == "verifyCode":
            return {
                "ok": False,
                "needs_code": True,
                "error": "Bambu sent a verification code to your email. Enter it to finish sign-in.",
            }
        access = self._persist_login_tokens(data)
        if not access:
            message = data.get("message") or data.get("error") or "Login did not return an access token"
            record_cloud_auth_error(str(message))
            return {"ok": False, "needs_code": False, "error": str(message)}
        return {"ok": True, "needs_code": False, "token_saved": True}

    def _login_with_env_password(self) -> str | None:
        email = os.environ.get("BAMBU_CLOUD_EMAIL", "").strip()
        password = os.environ.get("BAMBU_CLOUD_PASSWORD", "").strip()
        if not email or not password:
            return None
        try:
            result = self.login(email, password)
            if result.get("ok"):
                return resolve_cloud_access_token()
            if result.get("needs_code"):
                logger.error(
                    "Bambu cloud login requires 2FA verification; use Settings sign-in or paste a MakerWorld token"
                )
                record_cloud_auth_error("login requires 2FA verification code")
            else:
                record_cloud_auth_error(result.get("error") or "email/password login failed")
            return None
        except Exception as exc:
            logger.exception("Bambu cloud login failed")
            record_cloud_auth_error(f"email/password login failed: {exc}")
            return None

    def _try_refresh_token(self) -> str | None:
        refresh = cloud_refresh_token_from_db() or resolve_cloud_access_token()
        if not refresh:
            return None
        try:
            resp = self._session.post(
                f"{API_BASE}/v1/user-service/user/refreshtoken",
                json={"refreshToken": refresh},
                timeout=30,
            )
            if resp.status_code == 401:
                return None
            resp.raise_for_status()
            data = resp.json() if resp.content else {}
            return self._persist_login_tokens(data)
        except Exception:
            logger.exception("Bambu cloud token refresh failed")
            return None

    def _recover_from_401(self) -> str | None:
        """Attempt refresh, then email/password re-login. Returns a new token or None."""
        if not self._refresh_attempted:
            self._refresh_attempted = True
            token = self._try_refresh_token()
            if token:
                logger.info("Recovered Bambu cloud auth via refresh token")
                return token
        if not self._password_relogin_attempted:
            self._password_relogin_attempted = True
            token = self._login_with_env_password()
            if token:
                logger.info("Recovered Bambu cloud auth via email/password")
                return token
        return None

    def _ensure_token(self) -> str | None:
        token = resolve_cloud_access_token()
        if token:
            return token
        if self._session_token:
            return self._session_token
        return self._login_with_env_password()

    def _invalidate_session(self) -> None:
        self._session_token = None
        self._user_id = None
        self._devices = None

    def _headers(self) -> dict[str, str]:
        token = self._ensure_token()
        if not token:
            return {}
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    def _request_with_auth(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        timeout: int = 30,
    ) -> requests.Response:
        resp = self._session.request(
            method,
            url,
            headers=self._headers(),
            params=params,
            json=json_body,
            timeout=timeout,
        )
        if resp.status_code != 401:
            return resp
        self._invalidate_session()
        recovered = self._recover_from_401()
        if not recovered:
            message = "Bambu cloud token rejected (401). Paste a fresh MakerWorld token or sign in again."
            record_cloud_auth_error(message)
            raise CloudAuthError(message)
        resp = self._session.request(
            method,
            url,
            headers=self._headers(),
            params=params,
            json=json_body,
            timeout=timeout,
        )
        if resp.status_code == 401:
            message = "Bambu cloud token rejected (401). Paste a fresh MakerWorld token or sign in again."
            record_cloud_auth_error(message)
            raise CloudAuthError(message)
        return resp

    def validate_access_token(self, token: str) -> dict[str, Any]:
        """Probe a candidate token before saving it."""
        clean = (token or "").strip()
        if not clean:
            return {"ok": False, "error": "Token is empty"}
        try:
            resp = self._session.get(
                f"{API_BASE}/v1/design-user-service/my/preference",
                headers={"Authorization": f"Bearer {clean}", "Content-Type": "application/json"},
                timeout=30,
            )
            if resp.status_code == 401:
                return {"ok": False, "error": "Bambu rejected this token (expired or invalid)"}
            resp.raise_for_status()
            return {"ok": True}
        except CloudAuthError as exc:
            return {"ok": False, "error": str(exc)}
        except Exception as exc:
            return {"ok": False, "error": f"Could not validate token: {exc}"}

    def probe_auth(self) -> dict[str, Any]:
        if not self.is_configured():
            return {"ok": False, "error": "cloud not configured"}
        try:
            resp = self._request_with_auth(
                "GET",
                f"{API_BASE}/v1/design-user-service/my/preference",
            )
            resp.raise_for_status()
            record_cloud_auth_ok()
            return {"ok": True}
        except CloudAuthError as exc:
            return {"ok": False, "error": str(exc)}
        except Exception as exc:
            record_cloud_auth_error(str(exc))
            return {"ok": False, "error": str(exc)}

    def get_user_id(self) -> int | None:
        if self._user_id is not None:
            return self._user_id
        if not self.is_configured():
            return None
        try:
            resp = self._request_with_auth(
                "GET",
                f"{API_BASE}/v1/design-user-service/my/preference",
            )
            resp.raise_for_status()
            record_cloud_auth_ok()
            uid = resp.json().get("uid")
            if isinstance(uid, int):
                self._user_id = uid
            return self._user_id
        except CloudAuthError:
            raise
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
            resp = self._request_with_auth(
                "GET",
                f"{API_BASE}/v1/iot-service/api/user/bind",
            )
            resp.raise_for_status()
            record_cloud_auth_ok()
            data = resp.json()
            devices = data.get("devices") or []
            self._devices = devices if isinstance(devices, list) else []
            return self._devices
        except CloudAuthError:
            raise
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

    def fetch_tasks(
        self,
        after: str | None = None,
        limit: int = 20,
        *,
        device_id: str | None | object = ...,
    ) -> list[dict[str, Any]]:
        """Fetch recent cloud tasks.

        device_id:
          - Ellipsis (default): use BAMBU_CLOUD_DEVICE_ID / BAMBU_SERIAL when set
          - None: do not send deviceId (full account history)
          - str: filter to that device
        """
        if not self.is_configured():
            return []
        params: dict[str, Any] = {"limit": limit}
        if device_id is ...:
            resolved = os.environ.get("BAMBU_CLOUD_DEVICE_ID") or os.environ.get("BAMBU_SERIAL")
            if resolved:
                params["deviceId"] = resolved.strip()
        elif device_id:
            params["deviceId"] = str(device_id).strip()
        if after:
            params["after"] = after
        try:
            resp = self._request_with_auth(
                "GET",
                f"{API_BASE}/v1/user-service/my/tasks",
                params=params,
            )
            resp.raise_for_status()
            record_cloud_auth_ok()
            data = resp.json()
            if isinstance(data, dict):
                return data.get("hits") or data.get("tasks") or data.get("data") or []
            if isinstance(data, list):
                return data
            return []
        except CloudAuthError:
            raise
        except Exception:
            logger.exception("Failed to fetch Bambu cloud tasks")
            return []

    def fetch_tasks_for_printer(self, limit: int = 50) -> list[dict[str, Any]]:
        """Device-filtered tasks, merged with account history for this printer serial.

        Bambu's deviceId query param sometimes omits jobs that still carry our
        serial on the task payload (seen when looking for a missing Benchy).
        """
        serial = (
            os.environ.get("BAMBU_CLOUD_DEVICE_ID")
            or os.environ.get("BAMBU_SERIAL")
            or self.resolve_serial()
            or ""
        ).strip()
        by_id: dict[str, dict[str, Any]] = {}
        for task in self.fetch_tasks(limit=limit):
            task_id = str(task.get("id") or task.get("taskId") or "")
            if task_id:
                by_id[task_id] = task
        try:
            account_tasks = self.fetch_tasks(limit=limit, device_id=None)
        except CloudAuthError:
            raise
        except Exception:
            account_tasks = []
        for task in account_tasks:
            task_id = str(task.get("id") or task.get("taskId") or "")
            if not task_id:
                continue
            task_device = str(task.get("deviceId") or task.get("device_id") or "").strip()
            if serial and task_device and task_device != serial:
                continue
            # Prefer the device-filtered hit when both exist; otherwise add.
            by_id.setdefault(task_id, task)
        # Newest-first like the cloud API (higher/more recent ids tend to come first).
        return sorted(
            by_id.values(),
            key=lambda t: str(t.get("id") or t.get("taskId") or ""),
            reverse=True,
        )

    def _get_json(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        resp = self._request_with_auth("GET", f"{API_BASE}{path}", params=params)
        if resp.status_code in {403, 404}:
            return None
        resp.raise_for_status()
        return resp.json() if resp.content else None

    def fetch_printed_plates(self, limit: int = 50) -> list[dict[str, Any]]:
        """Alternate history endpoint Handy may use; shape varies."""
        try:
            data = self._get_json(
                "/v1/user-service/my/task/printedplates",
                params={"limit": limit},
            )
        except CloudAuthError:
            raise
        except Exception:
            logger.exception("Failed to fetch printed plates")
            return []
        if data is None:
            return []
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("hits", "plates", "data", "list", "tasks"):
                raw = data.get(key)
                if isinstance(raw, list):
                    return raw
                if isinstance(raw, dict) and isinstance(raw.get("hits"), list):
                    return raw["hits"]
        return []

    def fetch_iot_print_jobs(self, limit: int = 50) -> list[dict[str, Any]]:
        """GET /v1/iot-service/api/user/print — another print-history surface."""
        serial = (
            os.environ.get("BAMBU_CLOUD_DEVICE_ID")
            or os.environ.get("BAMBU_SERIAL")
            or self.resolve_serial()
            or ""
        ).strip()
        params: dict[str, Any] = {"limit": limit}
        if serial:
            params["device_id"] = serial
        try:
            data = self._get_json("/v1/iot-service/api/user/print", params=params)
        except CloudAuthError:
            raise
        except Exception:
            logger.exception("Failed to fetch iot print jobs")
            return []
        if data is None:
            return []
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            inner = data.get("data") if isinstance(data.get("data"), dict) else data
            if isinstance(inner, dict):
                for key in ("jobs", "prints", "list", "hits"):
                    raw = inner.get(key)
                    if isinstance(raw, list):
                        return raw
            for key in ("jobs", "prints", "list", "hits", "data"):
                raw = data.get(key)
                if isinstance(raw, list):
                    return raw
        return []

    def fetch_task_detail(self, task_id: str) -> dict[str, Any] | None:
        if not self.is_configured() or not task_id:
            return None
        try:
            resp = self._request_with_auth(
                "GET",
                f"{API_BASE}/v1/user-service/my/task/{task_id}",
            )
            if resp.status_code in {403, 404}:
                return None
            resp.raise_for_status()
            return resp.json()
        except CloudAuthError:
            raise
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
                # 254/255 = external spool / unknown — never invent an AMS slot.
                if tray_index >= 254 or tray_index < 0:
                    ams_slot = None
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
    ) -> int | None:
        """Map slicer filament id → physical AMS slot (1–4).

        Slicer filament ids are NOT AMS tray numbers. Without ams_mapping from
        Bambu, return None so we do not invent slot 1 (a prior bug that deducted
        the wrong spool whenever cloud tasks omitted mapping).
        """
        if not ams_mapping:
            return None
        slicer_index = max(0, int(filament_id) - 1)
        if slicer_index >= len(ams_mapping):
            return None
        tray_index = int(ams_mapping[slicer_index])
        if tray_index >= 254 or tray_index < 0:
            return None
        return max(1, min(4, tray_index + 1))

    def extract_filament_usages(
        self,
        task: dict[str, Any],
        ams_mapping_override: list[int] | None = None,
    ) -> list[dict[str, Any]]:
        ams_mapping = ams_mapping_override or self.extract_ams_mapping(task)

        plate_usages: list[dict[str, Any]] = []
        profile = task.get("profile") or task
        plates = profile.get("plates") or task.get("plates") or []
        for plate in plates:
            for filament in plate.get("filaments") or []:
                color = filament.get("color") or ""
                if color and not color.startswith("#"):
                    color = f"#{color[:6]}"
                filament_id = int(filament.get("id") or len(plate_usages) + 1)
                plate_usages.append(
                    {
                        "ams_slot": self.map_slicer_filament_to_ams_slot(filament_id, ams_mapping),
                        "material": (filament.get("type") or "UNKNOWN").upper(),
                        "color": color or None,
                        "used_g": ceil_usage_g(float(filament.get("used_g") or 0)),
                        "used_m": float(filament.get("used_m") or 0) if filament.get("used_m") else None,
                    }
                )

        # MQTT/cloud ams_mapping is authoritative for tray choice. Prefer plates + mapping.
        if plate_usages and ams_mapping:
            return plate_usages

        detail_usages = self._usages_from_ams_detail_mapping(task)
        if detail_usages:
            if ams_mapping:
                for index, usage in enumerate(detail_usages, start=1):
                    usage["ams_slot"] = self.map_slicer_filament_to_ams_slot(index, ams_mapping)
            return detail_usages

        if plate_usages:
            return plate_usages

        if task.get("weight"):
            return [
                {
                    "ams_slot": None,
                    "material": "UNKNOWN",
                    "color": None,
                    "used_g": ceil_usage_g(float(task.get("weight") or 0)),
                    "used_m": None,
                }
            ]
        return []
