"""Resolve Bambu cloud credentials from env vars or app settings (server volume)."""

from __future__ import annotations

import os

from db import connect, get_setting, set_setting

BAMBU_CLOUD_TOKEN_SETTING = "bambu_cloud_access_token"


def cloud_access_token_from_env() -> str | None:
    raw = os.environ.get("BAMBU_CLOUD_ACCESS_TOKEN", "").strip()
    return raw or None


def cloud_access_token_from_db() -> str | None:
    with connect() as conn:
        raw = get_setting(conn, BAMBU_CLOUD_TOKEN_SETTING)
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
    return "none"


def save_cloud_access_token(token: str | None) -> None:
    with connect() as conn:
        if token:
            set_setting(conn, BAMBU_CLOUD_TOKEN_SETTING, token.strip())
        else:
            conn.execute("DELETE FROM app_settings WHERE key = ?", (BAMBU_CLOUD_TOKEN_SETTING,))
