"""Bambu MQTT client — cloud broker (default) or optional local printer MQTT."""

from __future__ import annotations

import json
import logging
import os
import ssl
import threading
import time
from typing import TYPE_CHECKING, Any, Callable

import paho.mqtt.client as mqtt

if TYPE_CHECKING:
    from bambu.cloud_sync import BambuCloudClient

logger = logging.getLogger("bambu.mqtt")


def parse_trays_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    print_data = payload.get("print") or {}
    ams_data = payload.get("ams") or print_data.get("ams") or {}
    trays: dict[str, Any] = {}
    for unit in ams_data.get("ams") or []:
        for index, tray in enumerate(unit.get("tray") or [], start=1):
            slot = str(int(tray.get("id", index - 1)) + 1) if str(tray.get("id", "")).isdigit() else str(index)
            tag_uid = tray.get("tag_uid")
            if tag_uid and set(str(tag_uid).strip("0")) == set():
                tag_uid = None
            trays[slot] = {
                "tray_type": tray.get("tray_type"),
                "tray_color": tray.get("tray_color"),
                "tray_info_idx": tray.get("tray_info_idx"),
                "tag_uid": tag_uid,
                "remain": tray.get("remain"),
            }
    return trays


def record_mqtt_diagnostics(payload: dict[str, Any]) -> None:
    from datetime import datetime, timezone

    from db import connect, set_sync_state

    print_data = payload.get("print") or {}
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with connect() as conn:
        set_sync_state(conn, "mqtt_last_message_at", now)
        if print_data.get("msg") == 0:
            set_sync_state(conn, "mqtt_last_pushall_at", now)
            trays = parse_trays_from_payload(payload)
            set_sync_state(conn, "mqtt_last_pushall_tray_count", str(len(trays)))
            set_sync_state(
                conn,
                "mqtt_last_pushall_has_ams",
                "yes" if print_data.get("ams") else "no",
            )


class BambuMqttClient:
    def __init__(
        self,
        cloud_client: BambuCloudClient | None = None,
        on_print_complete: Callable[[dict[str, Any]], None] | None = None,
        on_state_update: Callable[[dict[str, Any], dict[str, Any]], None] | None = None,
    ) -> None:
        self.cloud = cloud_client
        self.on_print_complete = on_print_complete
        self.on_state_update = on_state_update
        self._client: mqtt.Client | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._last_state = "IDLE"
        self._last_pushall = 0.0
        self._mode: str | None = None

    @staticmethod
    def config() -> dict[str, str]:
        return {
            "ip": os.environ.get("BAMBU_PRINTER_IP", "").strip(),
            "serial": os.environ.get("BAMBU_SERIAL", "").strip(),
            "access_code": os.environ.get("BAMBU_LAN_ACCESS_CODE", "").strip(),
        }

    def connection_mode(self) -> str | None:
        if os.environ.get("BAMBU_MQTT_MODE", "auto").lower() == "local":
            return "local" if self._local_ready() else None
        if os.environ.get("BAMBU_MQTT_MODE", "auto").lower() == "cloud":
            return "cloud" if self._cloud_ready() else None

        # auto: prefer cloud when configured — deploy host often cannot route to printer LAN IP
        if self._cloud_ready():
            return "cloud"
        if self._local_ready():
            return "local"
        return None

    def _cloud_ready(self) -> bool:
        return bool(self.cloud and self.cloud.is_configured() and self._resolve_serial())

    def _local_ready(self) -> bool:
        serial = self._resolve_serial()
        return bool(self._resolve_ip() and serial and self._resolve_access_code())

    def _resolve_serial(self) -> str:
        cfg = self.config()
        if cfg["serial"]:
            return cfg["serial"]
        if self.cloud and self.cloud.is_configured():
            return self.cloud.resolve_serial()
        return ""

    def _resolve_ip(self) -> str:
        return self.config()["ip"]

    def _resolve_access_code(self) -> str:
        cfg = self.config()
        if cfg["access_code"]:
            return cfg["access_code"]
        if self.cloud and self.cloud.is_configured():
            return self.cloud.resolve_access_code()
        return ""

    def is_configured(self) -> bool:
        return self.connection_mode() is not None

    def start(self) -> None:
        mode = self.connection_mode()
        if not mode:
            logger.info("Bambu MQTT not configured; skipping (set cloud credentials and/or printer IP + access code)")
            return
        if self._thread and self._thread.is_alive():
            return
        self._mode = mode
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
                mode = self.connection_mode()
                if not mode:
                    logger.warning("Bambu MQTT no longer configured; stopping reconnect loop")
                    return
                self._mode = mode
                self._connect_once()
            except Exception:
                logger.exception("MQTT connection error; retrying in 30s")
            time.sleep(30)

    def _connect_once(self) -> None:
        if self._mode == "cloud":
            self._connect_cloud()
        else:
            self._connect_local()

    def _connect_cloud(self) -> None:
        if not self.cloud:
            return
        serial = self._resolve_serial()
        token = self.cloud._ensure_token()
        user_id = self.cloud.get_user_id()
        if not serial or not token or user_id is None:
            logger.error("Cloud MQTT missing serial, token, or user id")
            return

        broker = self.cloud.get_mqtt_broker()
        topic_report = f"device/{serial}/report"
        username = f"u_{user_id}"

        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv311)
        client.username_pw_set(username, token)
        client.tls_set(cert_reqs=ssl.CERT_NONE)
        client.tls_insecure_set(True)

        topic_request = f"device/{serial}/request"

        def on_connect(client, userdata, flags, reason_code, properties=None):
            if reason_code == 0 or str(reason_code) == "Success":
                logger.info("Connected to Bambu cloud MQTT (%s)", broker)
                client.subscribe(topic_report)
                self._enable_ams_tray_reads(client, topic_request)
                self._request_pushall(client, topic_request)
            else:
                logger.error("Cloud MQTT connect failed: %s", reason_code)

        client.on_connect = on_connect
        client.on_message = self._make_on_message()
        self._client = client
        client.connect(broker, 8883, keepalive=60)
        client.loop_start()
        while not self._stop.is_set():
            if time.time() - self._last_pushall > 60:
                self._request_pushall(client, topic_request)
            time.sleep(1)
        client.loop_stop()
        client.disconnect()

    def _connect_local(self) -> None:
        ip = self._resolve_ip()
        serial = self._resolve_serial()
        access_code = self._resolve_access_code()
        if not ip or not serial or not access_code:
            logger.error("Local MQTT missing printer IP, serial, or access code")
            return

        topic_report = f"device/{serial}/report"
        topic_request = f"device/{serial}/request"

        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv311)
        client.username_pw_set("bblp", access_code)
        client.tls_set(cert_reqs=ssl.CERT_NONE)
        client.tls_insecure_set(True)

        def on_connect(client, userdata, flags, reason_code, properties=None):
            if reason_code == 0 or str(reason_code) == "Success":
                logger.info("Connected to Bambu local MQTT (%s)", ip)
                client.subscribe(topic_report)
                self._enable_ams_tray_reads(client, topic_request)
                self._request_pushall(client, topic_request)
            else:
                logger.error("Local MQTT connect failed: %s", reason_code)

        client.on_connect = on_connect
        client.on_message = self._make_on_message()
        self._client = client
        client.connect(ip, 8883, keepalive=60)
        client.loop_start()
        while not self._stop.is_set():
            if time.time() - self._last_pushall > 60:
                self._request_pushall(client, topic_request)
            time.sleep(1)
        client.loop_stop()
        client.disconnect()

    def _make_on_message(self):
        def on_message(client, userdata, msg):
            try:
                payload = json.loads(msg.payload.decode("utf-8"))
            except json.JSONDecodeError:
                return
            self._handle_message(payload)

        return on_message

    def _enable_ams_tray_reads(self, client: mqtt.Client, topic_request: str) -> None:
        payload = json.dumps(
            {
                "system": {
                    "sequence_id": "0",
                    "command": "ams_user_setting",
                    "ams_id": 0,
                    "tray_read_option": True,
                }
            }
        )
        client.publish(topic_request, payload)

    def _request_pushall(self, client: mqtt.Client, topic_request: str) -> None:
        start_payload = json.dumps({"pushing": {"sequence_id": "0", "command": "start"}})
        client.publish(topic_request, start_payload)
        payload = json.dumps({"pushing": {"sequence_id": "0", "command": "pushall"}})
        client.publish(topic_request, payload)
        self._last_pushall = time.time()
        for slot_id in range(4):
            rfid_payload = json.dumps(
                {
                    "print": {
                        "sequence_id": str(slot_id + 1),
                        "command": "ams_get_rfid",
                        "ams_id": 0,
                        "slot_id": slot_id,
                    }
                }
            )
            client.publish(topic_request, rfid_payload)

    def _handle_message(self, payload: dict[str, Any]) -> None:
        record_mqtt_diagnostics(payload)
        print_data = payload.get("print") or {}
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

        trays = parse_trays_from_payload(payload)
        if trays:
            logger.info("AMS MQTT trays parsed for slots: %s", ", ".join(sorted(trays.keys())))

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
