"""One-shot MQTT probe to pull AMS tray state from the printer."""

from __future__ import annotations

import json
import logging
import ssl
import threading
import time
from typing import Any

import paho.mqtt.client as mqtt

from bambu.mqtt_client import BambuMqttClient, parse_trays_from_payload, record_mqtt_diagnostics

logger = logging.getLogger("bambu.mqtt_probe")


def probe_printer_mqtt(timeout: float = 15.0) -> dict[str, Any]:
    client = BambuMqttClient()
    mode = client.connection_mode()
    if mode != "local":
        return {
            "ok": False,
            "mode": mode,
            "error": "AMS refresh needs local MQTT (printer IP, serial, and LAN access code in Portainer).",
        }

    ip = client._resolve_ip()
    serial = client._resolve_serial()
    access_code = client._resolve_access_code()
    if not ip or not serial or not access_code:
        return {"ok": False, "mode": mode, "error": "Missing printer IP, serial, or LAN access code."}

    topic_report = f"device/{serial}/report"
    topic_request = f"device/{serial}/request"
    result: dict[str, Any] = {
        "ok": False,
        "mode": mode,
        "connected": False,
        "events": [],
        "trays": {},
        "printer": {},
    }
    trays_event = threading.Event()
    connected_event = threading.Event()

    def on_connect(mqtt_client, userdata, flags, reason_code, properties=None):
        if reason_code == 0 or str(reason_code) == "Success":
            result["connected"] = True
            connected_event.set()
            mqtt_client.subscribe(topic_report)
            result["events"].append("subscribed")
            _enable_ams_tray_reads(mqtt_client, topic_request)
            _request_pushall(mqtt_client, topic_request)
            result["events"].append("pushall_sent")
        else:
            result["error"] = f"MQTT connect failed: {reason_code}"

    def on_message(mqtt_client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except json.JSONDecodeError:
            return

        print_data = payload.get("print") or {}
        if print_data.get("msg") == 0:
            result["events"].append("pushall_received")
            has_ams = bool(print_data.get("ams"))
            result["events"].append(f"pushall_has_ams={'yes' if has_ams else 'no'}")
            if has_ams and isinstance(print_data.get("ams"), dict):
                result["pushall_ams_keys"] = sorted(print_data["ams"].keys())

        record_mqtt_diagnostics(payload)

        result["printer"] = {
            "gcode_state": print_data.get("gcode_state"),
            "gcode_file": print_data.get("gcode_file"),
            "subtask_name": print_data.get("subtask_name"),
        }

        trays = parse_trays_from_payload(payload)
        if trays:
            result["trays"] = trays
            result["events"].append(f"trays_parsed={','.join(sorted(trays.keys()))}")
            from bambu.print_processor import store_live_state

            store_live_state(result["printer"], trays)
            trays_event.set()

    probe = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv311)
    probe.username_pw_set("bblp", access_code)
    probe.tls_set(cert_reqs=ssl.CERT_NONE)
    probe.tls_insecure_set(True)
    probe.on_connect = on_connect
    probe.on_message = on_message

    try:
        probe.connect(ip, 8883, keepalive=60)
    except OSError as exc:
        return {"ok": False, "mode": mode, "error": f"Could not reach printer at {ip}:8883 — {exc}"}

    probe.loop_start()
    if not connected_event.wait(timeout=min(timeout, 8.0)):
        probe.loop_stop()
        probe.disconnect()
        return {
            **result,
            "error": f"Timed out connecting to printer MQTT at {ip}:8883",
        }

    if not trays_event.wait(timeout=max(1.0, timeout - 2.0)):
        result["events"].append("no_trays_before_timeout")

    probe.loop_stop()
    probe.disconnect()

    result["ok"] = bool(result["trays"])
    if not result["ok"] and "error" not in result:
        result["error"] = (
            "Connected to printer MQTT but no AMS tray data arrived. "
            "Check that AMS is powered and trays are loaded; P1S only sends tray arrays in pushall responses."
        )
    return result


def _enable_ams_tray_reads(client: mqtt.Client, topic_request: str) -> None:
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


def _request_pushall(client: mqtt.Client, topic_request: str) -> None:
    client.publish(topic_request, json.dumps({"pushing": {"sequence_id": "0", "command": "start"}}))
    client.publish(topic_request, json.dumps({"pushing": {"sequence_id": "0", "command": "pushall"}}))
    for slot_id in range(4):
        client.publish(
            topic_request,
            json.dumps(
                {
                    "print": {
                        "sequence_id": str(slot_id + 1),
                        "command": "ams_get_rfid",
                        "ams_id": 0,
                        "slot_id": slot_id,
                    }
                }
            ),
        )
