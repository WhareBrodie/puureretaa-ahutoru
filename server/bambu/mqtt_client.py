"""Bambu LAN MQTT client for live printer and AMS state."""

from __future__ import annotations

import json
import logging
import os
import ssl
import threading
import time
from typing import Any, Callable

import paho.mqtt.client as mqtt

logger = logging.getLogger("bambu.mqtt")

FINISH_STATES = {"FINISH", "FAILED", "IDLE"}


class BambuMqttClient:
    def __init__(
        self,
        on_print_complete: Callable[[dict[str, Any]], None] | None = None,
        on_state_update: Callable[[dict[str, Any], dict[str, Any]], None] | None = None,
    ) -> None:
        self.on_print_complete = on_print_complete
        self.on_state_update = on_state_update
        self._client: mqtt.Client | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._last_state = "IDLE"
        self._last_pushall = 0.0
        self._connected = False

    @staticmethod
    def config() -> dict[str, str]:
        return {
            "ip": os.environ.get("BAMBU_PRINTER_IP", ""),
            "serial": os.environ.get("BAMBU_SERIAL", ""),
            "access_code": os.environ.get("BAMBU_LAN_ACCESS_CODE", ""),
        }

    def is_configured(self) -> bool:
        cfg = self.config()
        return bool(cfg["ip"] and cfg["serial"] and cfg["access_code"])

    def start(self) -> None:
        if not self.is_configured():
            logger.info("Bambu MQTT not configured; skipping")
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="bambu-mqtt")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._client:
            self._client.loop_stop()
            self._client.disconnect()

    def _run_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._connect_once()
            except Exception:
                logger.exception("MQTT connection error; retrying in 30s")
            time.sleep(30)

    def _connect_once(self) -> None:
        cfg = self.config()
        serial = cfg["serial"]
        topic_report = f"device/{serial}/report"
        topic_request = f"device/{serial}/request"

        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv311)
        client.username_pw_set("bblp", cfg["access_code"])
        client.tls_set(cert_reqs=ssl.CERT_NONE)
        client.tls_insecure_set(True)

        def on_connect(client, userdata, flags, reason_code, properties=None):
            if reason_code == 0 or str(reason_code) == "Success":
                logger.info("Connected to Bambu MQTT")
                self._connected = True
                client.subscribe(topic_report)
                self._request_pushall(client, topic_request)
            else:
                logger.error("MQTT connect failed: %s", reason_code)

        def on_message(client, userdata, msg):
            try:
                payload = json.loads(msg.payload.decode("utf-8"))
            except json.JSONDecodeError:
                return
            self._handle_message(payload)

        client.on_connect = on_connect
        client.on_message = on_message
        self._client = client
        client.connect(cfg["ip"], 8883, keepalive=60)
        client.loop_start()
        while not self._stop.is_set():
            if time.time() - self._last_pushall > 300:
                self._request_pushall(client, topic_request)
            time.sleep(1)
        client.loop_stop()
        client.disconnect()

    def _request_pushall(self, client: mqtt.Client, topic_request: str) -> None:
        payload = json.dumps({"pushing": {"sequence_id": "0", "command": "pushall"}})
        client.publish(topic_request, payload)
        self._last_pushall = time.time()

    def _handle_message(self, payload: dict[str, Any]) -> None:
        print_data = payload.get("print") or {}
        ams_data = payload.get("ams") or {}
        gcode_state = print_data.get("gcode_state", self._last_state)

        printer_state = {
            "gcode_state": gcode_state,
            "gcode_file": print_data.get("gcode_file"),
            "subtask_name": print_data.get("subtask_name"),
            "task_id": print_data.get("task_id"),
            "mc_percent": print_data.get("mc_percent"),
            "mc_remaining_time": print_data.get("mc_remaining_time"),
            "layer_num": print_data.get("layer_num"),
            "total_layer_num": print_data.get("total_layer_num"),
        }

        trays: dict[str, Any] = {}
        ams_units = ams_data.get("ams") or []
        if ams_units:
            unit = ams_units[0]
            for index, tray in enumerate(unit.get("tray") or [], start=1):
                trays[str(index)] = {
                    "tray_type": tray.get("tray_type"),
                    "tray_color": tray.get("tray_color"),
                    "tray_info_idx": tray.get("tray_info_idx"),
                    "tag_uid": tray.get("tag_uid"),
                    "remain": tray.get("remain"),
                }

        if self.on_state_update:
            self.on_state_update(printer_state, trays)

        previous = self._last_state
        self._last_state = gcode_state
        if previous in {"RUNNING", "PAUSE"} and gcode_state in {"FINISH", "FAILED"}:
            if self.on_print_complete:
                self.on_print_complete(
                    {
                        **printer_state,
                        "status": "completed" if gcode_state == "FINISH" else "failed",
                        "completion_percent": print_data.get("mc_percent") or 100,
                    }
                )
