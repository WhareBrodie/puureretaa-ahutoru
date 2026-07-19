#!/usr/bin/env python3
"""Pūreretā Ahutoru web server — static SPA plus filament inventory API."""

from __future__ import annotations

import cgi
import json
import mimetypes
import os
import re
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

SERVER_DIR = Path(__file__).resolve().parent
if str(SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(SERVER_DIR))

from db import get_data_dir, get_root, init_db
from routes import ams, csv_io, dashboard, locations, prints, settings, spools

ROOT = get_root()
DIST = ROOT / "dist"
STATIC = DIST if DIST.is_dir() else ROOT / "frontend" / "dist"

ID_RE = re.compile(r"^/api/([^/]+)(?:/(\d+))?(?:/([^/]+))?(?:/([^/]+))?$")


class PureretaHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(STATIC if STATIC.is_dir() else ROOT), **kwargs)

    def log_message(self, format: str, *args: Any) -> None:
        sys.stderr.write("%s - - [%s] %s\n" % (self.address_string(), self.log_date_time_string(), format % args))

    def end_json(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def end_text(self, status: int, text: str, content_type: str = "text/plain; charset=utf-8") -> None:
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            raise ValueError("Expected JSON body")
        raw = self.rfile.read(length)
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("JSON body must be an object")
        return data

    def parse_path(self) -> tuple[list[str], dict[str, list[str]]]:
        parsed = urlparse(self.path)
        parts = [part for part in parsed.path.split("/") if part]
        return parts, parse_qs(parsed.query)

    def serve_spa_or_static(self) -> None:
        path = urlparse(self.path).path
        if STATIC.is_dir() and not path.startswith("/api/"):
            if path != "/" and not (STATIC / path.lstrip("/")).is_file():
                self.path = "/index.html"
        super().do_GET()

    def do_GET(self) -> None:
        parts, query = self.parse_path()
        try:
            if parts == ["api", "health"]:
                self.end_json(200, {"ok": True})
                return

            if parts == ["api", "dashboard"]:
                self.end_json(200, dashboard.get_dashboard())
                return
            if parts == ["api", "stats"]:
                self.end_json(200, dashboard.get_stats())
                return
            if parts == ["api", "alerts"]:
                self.end_json(
                    200,
                    {
                        "low_stock": dashboard.get_low_stock_alerts(),
                        "drying": dashboard.get_drying_alerts(),
                        "reorder": dashboard.get_reorder_suggestions(),
                    },
                )
            if parts == ["api", "settings"]:
                self.end_json(200, settings.get_settings())
                return

            if parts == ["api", "locations"]:
                self.end_json(200, {"locations": locations.list_locations()})
                return

            if parts == ["api", "spools"]:
                material = query.get("material", [None])[0]
                low_stock = query.get("low_stock", ["false"])[0].lower() == "true"
                self.end_json(
                    200,
                    {"spools": spools.list_spools(material=material, low_stock_only=low_stock)},
                )
                return
            if len(parts) == 3 and parts[0] == "api" and parts[1] == "spools" and parts[2].isdigit():
                self.end_json(200, spools.get_spool(int(parts[2])))
                return

            if parts == ["api", "empty-spool-weights"]:
                self.end_json(
                    200,
                    {
                        "entries": spools.lookup_empty_spool_weights(
                            brand=query.get("brand", [None])[0],
                            model=query.get("model", [None])[0],
                        )
                    },
                )
                return

            if parts == ["api", "prints"]:
                pending = query.get("pending_review", ["false"])[0].lower() == "true"
                self.end_json(200, {"prints": prints.list_prints(pending_review_only=pending)})
                return
            if len(parts) == 3 and parts[0] == "api" and parts[1] == "prints" and parts[2].isdigit():
                self.end_json(200, prints.get_print(int(parts[2])))
                return

            if parts == ["api", "ams", "slots"]:
                self.end_json(200, {"slots": ams.list_ams_slots()})
                return
            if parts == ["api", "ams", "live"]:
                self.end_json(200, ams.get_live_printer_state())
                return
            if parts == ["api", "printer", "status"]:
                self.end_json(200, ams.get_live_printer_state())
                return

            if parts == ["api", "export", "csv"]:
                csv_text = csv_io.export_spools_csv()
                self.end_text(
                    200,
                    csv_text,
                    content_type="text/csv; charset=utf-8",
                )
                return

            if self.path.startswith("/api/photos/"):
                rel = self.path.removeprefix("/api/photos/")
                photo_path = get_data_dir() / "photos" / rel
                if photo_path.is_file():
                    data = photo_path.read_bytes()
                    ctype = mimetypes.guess_type(str(photo_path))[0] or "application/octet-stream"
                    self.send_response(200)
                    self.send_header("Content-Type", ctype)
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return

            if parts and parts[0] == "api":
                self.send_error(404)
                return
        except KeyError as exc:
            self.end_json(404, {"error": str(exc)})
            return
        except Exception as exc:  # noqa: BLE001
            self.end_json(400, {"error": str(exc)})
            return

        self.serve_spa_or_static()

    def do_POST(self) -> None:
        parts, _ = self.parse_path()
        try:
            if parts == ["api", "locations"]:
                self.end_json(201, locations.create_location(self.read_json_body()))
                return

            if parts == ["api", "spools"]:
                self.end_json(201, spools.create_spool(self.read_json_body()))
                return

            if len(parts) == 4 and parts[0] == "api" and parts[1] == "spools" and parts[3] == "calculate-weight":
                body = self.read_json_body()
                self.end_json(
                    200,
                    spools.calculate_remaining_from_scale(int(parts[2]), float(body["total_weight_g"])),
                )
                return

            if len(parts) == 4 and parts[0] == "api" and parts[1] == "spools" and parts[3] == "drying-log":
                self.end_json(201, spools.add_drying_log(int(parts[2]), self.read_json_body()))
                return

            if len(parts) == 4 and parts[0] == "api" and parts[1] == "spools" and parts[3] == "photo":
                self._handle_photo_upload(int(parts[2]))
                return

            if len(parts) == 4 and parts[0] == "api" and parts[1] == "spools" and parts[3] == "link-bambu-tag":
                body = self.read_json_body()
                self.end_json(
                    200,
                    spools.link_bambu_tag(int(parts[2]), body["tag_uid"], body.get("tray_info_idx")),
                )
                return

            if parts == ["api", "prints"]:
                self.end_json(201, prints.create_manual_print(self.read_json_body()))
                return

            if len(parts) == 4 and parts[0] == "api" and parts[1] == "prints" and parts[3] == "review":
                self.end_json(200, prints.resolve_print_review_v2(int(parts[2]), self.read_json_body()))
                return

            if parts == ["api", "import", "csv"]:
                body = self.read_json_body()
                result = csv_io.import_spools_csv(body.get("csv", ""), update_existing=bool(body.get("update_existing")))
                self.end_json(200, result)
                return

            if parts and parts[0] == "api":
                self.send_error(404)
                return
        except KeyError as exc:
            self.end_json(404, {"error": str(exc)})
            return
        except Exception as exc:  # noqa: BLE001
            self.end_json(400, {"error": str(exc)})
            return
        self.send_error(404)

    def do_PUT(self) -> None:
        parts, _ = self.parse_path()
        try:
            if len(parts) == 3 and parts[0] == "api" and parts[1] == "locations":
                self.end_json(200, locations.update_location(int(parts[2]), self.read_json_body()))
                return
            if len(parts) == 3 and parts[0] == "api" and parts[1] == "spools":
                self.end_json(200, spools.update_spool(int(parts[2]), self.read_json_body()))
                return
            if len(parts) == 4 and parts[0] == "api" and parts[1] == "ams" and parts[2] == "slots":
                self.end_json(200, ams.update_ams_slot(int(parts[3]), self.read_json_body()))
                return
            if parts == ["api", "settings"]:
                self.end_json(200, settings.update_settings(self.read_json_body()))
                return
            if parts and parts[0] == "api":
                self.send_error(404)
                return
        except KeyError as exc:
            self.end_json(404, {"error": str(exc)})
            return
        except Exception as exc:  # noqa: BLE001
            self.end_json(400, {"error": str(exc)})
            return
        self.send_error(404)

    def do_DELETE(self) -> None:
        parts, _ = self.parse_path()
        try:
            if len(parts) == 3 and parts[0] == "api" and parts[1] == "locations":
                locations.delete_location(int(parts[2]))
                self.end_json(200, {"ok": True})
                return
            if len(parts) == 3 and parts[0] == "api" and parts[1] == "spools":
                spools.delete_spool(int(parts[2]))
                self.end_json(200, {"ok": True})
                return
            if parts and parts[0] == "api":
                self.send_error(404)
                return
        except Exception as exc:  # noqa: BLE001
            self.end_json(400, {"error": str(exc)})
            return
        self.send_error(404)

    def _handle_photo_upload(self, spool_id: int) -> None:
        content_type = self.headers.get("Content-Type", "")
        if content_type.startswith("multipart/form-data"):
            form = cgi.FieldStorage(fp=self.rfile, headers=self.headers, environ={
                "REQUEST_METHOD": "POST",
                "CONTENT_TYPE": content_type,
            })
            if "photo" not in form:
                raise ValueError("photo field required")
            file_item = form["photo"]
            filename = getattr(file_item, "filename", "photo.jpg") or "photo.jpg"
            content = file_item.file.read() if file_item.file else b""
        else:
            length = int(self.headers.get("Content-Length", "0"))
            content = self.rfile.read(length)
            filename = self.headers.get("X-Filename", "photo.jpg")
        self.end_json(200, spools.save_photo(spool_id, filename, content))


def main() -> None:
    init_db(ROOT)
    port = int(os.environ.get("PORT", "8080"))
    server = ThreadingHTTPServer(("0.0.0.0", port), PureretaHandler)
    sys.stderr.write(f"Pūreretā Ahutoru listening on :{port}\n")
    server.serve_forever()


if __name__ == "__main__":
    main()
