"""FTPS gcode download and basic filament usage parsing."""

from __future__ import annotations

import io
import logging
import os
import re
import ssl
import zipfile
from ftplib import FTP_TLS
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from bambu.cloud_sync import BambuCloudClient

logger = logging.getLogger("bambu.ftps")

FILAMENT_CHANGE_RE = re.compile(
    r"; filament used \[g\] = (?P<used>[\d.]+).*?; filament_type = (?P<type>\w+)",
    re.IGNORECASE,
)
EXTRUDER_USAGE_RE = re.compile(r"; total filament used \[g\] = (?P<used>[\d.]+)", re.IGNORECASE)
MULTI_FILAMENT_RE = re.compile(
    r"; filament_type\s*=\s*(?P<type>\w+).*?; filament_colour\s*=\s*(?P<color>#[0-9A-Fa-f]{6})",
    re.IGNORECASE | re.DOTALL,
)


class BambuFtpsClient:
    def __init__(self, cloud_client: BambuCloudClient | None = None) -> None:
        self.cloud = cloud_client
        self.ip = os.environ.get("BAMBU_PRINTER_IP", "").strip()

    def _access_code(self) -> str:
        code = os.environ.get("BAMBU_LAN_ACCESS_CODE", "").strip()
        if code:
            return code
        if self.cloud and self.cloud.is_configured():
            return self.cloud.resolve_access_code()
        return ""

    def is_configured(self) -> bool:
        return bool(self.ip and self._access_code())

    def download_file(self, remote_path: str) -> bytes | None:
        if not self.is_configured() or not remote_path:
            return None
        try:
            ftp = FTP_TLS()
            ftp.context = ssl.create_default_context()
            ftp.connect(self.ip, 990, timeout=30)
            ftp.auth()
            ftp.prot_p()
            ftp.login("bblp", self._access_code())
            ftp.set_pasv(True)
            buf = io.BytesIO()
            ftp.retrbinary(f"RETR {remote_path}", buf.write)
            ftp.quit()
            return buf.getvalue()
        except Exception:
            logger.exception("FTPS download failed for %s", remote_path)
            return None

    def resolve_gcode_content(self, gcode_file: str) -> str | None:
        if not gcode_file:
            return None
        candidates = [gcode_file]
        if not gcode_file.startswith("/"):
            candidates.extend(
                [
                    f"/sdcard/{gcode_file}",
                    f"/cache/{gcode_file}",
                    f"/{gcode_file}",
                ]
            )
        for path in candidates:
            raw = self.download_file(path)
            if not raw:
                continue
            if path.endswith(".3mf") or raw[:2] == b"PK":
                return self._extract_gcode_from_3mf(raw)
            try:
                return raw.decode("utf-8", errors="replace")
            except Exception:
                continue
        return None

    @staticmethod
    def _extract_gcode_from_3mf(data: bytes) -> str | None:
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                for name in archive.namelist():
                    if name.endswith(".gcode"):
                        return archive.read(name).decode("utf-8", errors="replace")
        except Exception:
            logger.exception("Failed to extract gcode from 3mf")
        return None


def parse_filament_usage(gcode: str, completion_percent: float = 100) -> list[dict[str, Any]]:
    scale = max(0.0, min(completion_percent, 100.0)) / 100.0
    usages: list[dict[str, Any]] = []

    for match in FILAMENT_CHANGE_RE.finditer(gcode):
        usages.append(
            {
                "ams_slot": len(usages) + 1,
                "material": match.group("type").upper(),
                "color": None,
                "used_g": round(float(match.group("used")) * scale, 2),
                "used_m": None,
            }
        )

    if not usages:
        total = EXTRUDER_USAGE_RE.search(gcode)
        if total:
            usages.append(
                {
                    "ams_slot": 1,
                    "material": "UNKNOWN",
                    "color": None,
                    "used_g": round(float(total.group("used")) * scale, 2),
                    "used_m": None,
                }
            )

    return usages
