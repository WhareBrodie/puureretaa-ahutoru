"""Resolve Bambu cloud credentials from env vars or app settings (server volume)."""

from __future__ import annotations

import base64
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from db import connect, get_setting, get_sync_state, set_setting, set_sync_state

BAMBU_CLOUD_TOKEN_SETTING = "bambu_cloud_access_token"
BAMBU_CLOUD_REFRESH_SETTING = "bambu_cloud_refresh_token"
BAMBU_CLOUD_TOKEN_EXPIRES_SETTING = "bambu_cloud_token_expires_at"

CLOUD_AUTH_OK_KEY = "cloud_auth_ok_at"
CLOUD_AUTH_ERROR_KEY = "cloud_auth_error"
CLOUD_AUTH_ERROR_AT_KEY = "cloud_auth_error_at"
CLOUD_POLL_OK_KEY = "cloud_poll_ok_at"


def cloud_access_token_from_env() -> str | None:
    raw = os.environ.get("BAMBU_CLOUD_ACCESS_TOKEN", "").strip()
    return raw or None


def cloud_access_token_from_db() -> str | None:
    with connect() as conn:
        raw = get_setting(conn, BAMBU_CLOUD_TOKEN_SETTING)
    return raw.strip() if raw else None


def cloud_refresh_token_from_db() -> str | None:
    with connect() as conn:
        raw = get_setting(conn, BAMBU_CLOUD_REFRESH_SETTING)
    return raw.strip() if raw else None


def resolve_cloud_access_token() -> str | None:
    """App Settings token wins so you can refresh without Portainer; env is fallback."""
    return cloud_access_token_from_db() or cloud_access_token_from_env()


def cloud_credentials_configured() -> bool:
    return bool(
        resolve_cloud_access_token()
        or (os.environ.get("BAMBU_CLOUD_EMAIL") and os.environ.get("BAMBU_CLOUD_PASSWORD"))
    )


def cloud_token_source() -> str:
    if cloud_access_token_from_db():
        return "app"
    if cloud_access_token_from_env():
        return "env"
    if os.environ.get("BAMBU_CLOUD_EMAIL") and os.environ.get("BAMBU_CLOUD_PASSWORD"):
        return "email"
    return "none"


def _b64url_json(segment: str) -> dict[str, Any] | None:
    try:
        padded = segment + "=" * (-len(segment) % 4)
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
        data = json.loads(raw.decode("utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def jwt_expiry_iso(token: str | None) -> str | None:
    """Best-effort JWT exp claim → ISO UTC. Opaque tokens return None."""
    if not token or token.count(".") != 2:
        return None
    payload = _b64url_json(token.split(".")[1])
    if not payload:
        return None
    exp = payload.get("exp")
    if exp is None:
        return None
    try:
        return datetime.fromtimestamp(int(exp), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def expires_iso_from_expires_in(expires_in: Any) -> str | None:
    try:
        seconds = int(expires_in)
    except (TypeError, ValueError):
        return None
    if seconds <= 0:
        return None
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


def save_cloud_access_token(
    token: str | None,
    *,
    refresh_token: str | None = None,
    expires_at: str | None = None,
    expires_in: Any = None,
) -> None:
    with connect() as conn:
        if token:
            clean = token.strip()
            set_setting(conn, BAMBU_CLOUD_TOKEN_SETTING, clean)
            expiry = expires_at or expires_iso_from_expires_in(expires_in) or jwt_expiry_iso(clean)
            if expiry:
                set_setting(conn, BAMBU_CLOUD_TOKEN_EXPIRES_SETTING, expiry)
            else:
                conn.execute(
                    "DELETE FROM app_settings WHERE key = ?",
                    (BAMBU_CLOUD_TOKEN_EXPIRES_SETTING,),
                )
            if refresh_token:
                set_setting(conn, BAMBU_CLOUD_REFRESH_SETTING, refresh_token.strip())
        else:
            conn.execute("DELETE FROM app_settings WHERE key = ?", (BAMBU_CLOUD_TOKEN_SETTING,))
            conn.execute("DELETE FROM app_settings WHERE key = ?", (BAMBU_CLOUD_REFRESH_SETTING,))
            conn.execute(
                "DELETE FROM app_settings WHERE key = ?",
                (BAMBU_CLOUD_TOKEN_EXPIRES_SETTING,),
            )


def token_expires_at() -> str | None:
    with connect() as conn:
        stored = get_setting(conn, BAMBU_CLOUD_TOKEN_EXPIRES_SETTING)
        if stored:
            return stored
    return jwt_expiry_iso(resolve_cloud_access_token())


def record_cloud_auth_ok() -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with connect() as conn:
        set_sync_state(conn, CLOUD_AUTH_OK_KEY, now)
        set_sync_state(conn, CLOUD_AUTH_ERROR_KEY, "")
        set_sync_state(conn, CLOUD_AUTH_ERROR_AT_KEY, "")


def record_cloud_auth_error(message: str) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with connect() as conn:
        set_sync_state(conn, CLOUD_AUTH_ERROR_KEY, (message or "cloud auth failed")[:500])
        set_sync_state(conn, CLOUD_AUTH_ERROR_AT_KEY, now)


def record_cloud_poll_ok() -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with connect() as conn:
        set_sync_state(conn, CLOUD_POLL_OK_KEY, now)


def cloud_auth_status() -> dict[str, Any]:
    expires = token_expires_at()
    days_left: int | None = None
    expired = False
    if expires:
        try:
            exp_dt = datetime.fromisoformat(expires.replace("Z", "+00:00"))
            delta = exp_dt - datetime.now(timezone.utc)
            days_left = int(delta.total_seconds() // 86400)
            expired = delta.total_seconds() <= 0
        except ValueError:
            pass

    with connect() as conn:
        auth_error = get_sync_state(conn, CLOUD_AUTH_ERROR_KEY) or None
        auth_error_at = get_sync_state(conn, CLOUD_AUTH_ERROR_AT_KEY) or None
        auth_ok_at = get_sync_state(conn, CLOUD_AUTH_OK_KEY) or None
        poll_ok_at = get_sync_state(conn, CLOUD_POLL_OK_KEY) or None
        mqtt_at = get_sync_state(conn, "mqtt_last_message_at")

    if auth_error == "":
        auth_error = None
    if auth_error_at == "":
        auth_error_at = None

    return {
        "configured": cloud_credentials_configured(),
        "token_source": cloud_token_source(),
        "token_set": bool(resolve_cloud_access_token()),
        "has_refresh_token": bool(cloud_refresh_token_from_db()),
        "email_password_configured": bool(
            os.environ.get("BAMBU_CLOUD_EMAIL") and os.environ.get("BAMBU_CLOUD_PASSWORD")
        ),
        "expires_at": expires,
        "days_left": days_left,
        "expired": expired,
        "auth_ok_at": auth_ok_at,
        "auth_error": auth_error,
        "auth_error_at": auth_error_at,
        "poll_ok_at": poll_ok_at,
        "mqtt_last_message_at": mqtt_at,
        "healthy": bool(
            cloud_credentials_configured()
            and not expired
            and not auth_error
        ),
    }
