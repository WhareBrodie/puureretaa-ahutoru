"""FTPS gcode download and basic filament usage parsing."""

from __future__ import annotations

import io
import logging
import os
import re
import ssl
import zipfile
from ftplib import FTP_TLS
from typing import Any

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
    def __init__(self) -> None:
        self.ip = os.environ.get("BAMBU_PRINTER_IP", "")
        self.access_code = os.environ.get("BAMBU_LAN_ACCESS_CODE", "")

    def is_configured(self) -> bool:
        return bool(self.ip and self.access_code)

    def download_file(self, remote_path: str) -> bytes | None:
        if not self.is_configured() or not remote_path:
            return None
        try:
            ftp = FTP_TLS()
            ftp.context = ssl.create_default_context()
            ftp.context.check_hostname = False
            ftp.context.verify_mode = ssl.CERT_NONE
            ftp.connect(self.ip, 990, timeout=30)
            ftp.login("bblp", self.access_code)
            ftp.prot_p()
            buffer = io.BytesIO()
            ftp.retrbinary(f"RETR {remote_path}", buffer.write)
            ftp.quit()
            return buffer.getvalue()
        except Exception:
            logger.exception("FTPS download failed for %s", remote_path)
            return None

    def resolve_gcode_content(self, filename: str) -> str | None:
        if not filename:
            return None
        candidates = [
            filename,
            f"/sdcard/{filename}",
            f"cache/{filename}",
            f"/cache/{filename}",
        ]
        for path in candidates:
            data = self.download_file(path)
            if not data:
                continue
            if filename.lower().endswith(".3mf") or data[:2] == b"PK":
                return self._extract_gcode_from_3mf(data)
            return data.decode("utf-8", errors="ignore")
        return None

    @staticmethod
    def _extract_gcode_from_3mf(data: bytes) -> str | None:
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                gcode_files = [name for name in archive.namelist() if name.endswith(".gcode")]
                if not gcode_files:
                    return None
                return archive.read(gcode_files[0]).decode("utf-8", errors="ignore")
        except zipfile.BadZipFile:
            return None


def parse_filament_usage(gcode: str, completion_percent: float = 100.0) -> list[dict[str, Any]]:
    scale = max(0.0, min(completion_percent, 100.0)) / 100.0
    usages: list[dict[str, Any]] = []

    slot = 1
    for match in FILAMENT_CHANGE_RE.finditer(gcode):
        usages.append(
            {
                "ams_slot": slot,
                "material": match.group("type").upper(),
                "color": None,
                "used_g": round(float(match.group("used")) * scale, 2),
                "used_m": None,
            }
        )
        slot += 1

    if not usages:
        total_match = EXTRUDER_USAGE_RE.search(gcode)
        if total_match:
            usages.append(
                {
                    "ams_slot": 1,
                    "material": "UNKNOWN",
                    "color": None,
                    "used_g": round(float(total_match.group("used")) * scale, 2),
                    "used_m": None,
                }
            )

    return usages
