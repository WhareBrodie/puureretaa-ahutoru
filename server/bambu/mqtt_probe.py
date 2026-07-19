"""One-shot MQTT probe to pull AMS tray state from the printer."""

from __future__ import annotations

import json
import logging
import ssl
import threading
from typing import Any

import paho.mqtt.client as mqtt

from bambu.cloud_sync import BambuCloudClient
from bambu.mqtt_client import BambuMqttClient, parse_trays_from_payload, record_mqtt_diagnostics

logger = logging.getLogger("bambu.mqtt_probe")

DEPLOY_HOST_HINT = (
    "The app container runs on your deploy host, not your Mac — it must be able to reach the "
    "printer IP for local MQTT. If it cannot, set BAMBU_MQTT_MODE=cloud in Portainer (cloud token "
    "required) or fix routing/firewall to the printer LAN."
)


def probe_printer_mqtt(timeout: float = 20.0) -> dict[str, Any]:
    client = BambuMqttClient(cloud_client=BambuCloudClient())
    preferred = client.connection_mode()
    if not preferred:
        return {
            "ok": False,
            "mode": None,
            "error": "Bambu MQTT is not configured (cloud token and/or printer LAN vars).",
        }

    modes: list[str] = [preferred]
    if preferred == "local" and client._cloud_ready():
        modes.append("cloud")

    last_result: dict[str, Any] | None = None
    for mode in modes:
        last_result = _probe_once(client, mode, timeout)
        if last_result.get("ok"):
            return last_result
        if last_result.get("connected"):
            return last_result

    assert last_result is not None
    if preferred == "local" and "cloud" in modes and last_result.get("mode") == "cloud":
        last_result["note"] = "Local MQTT failed; tried cloud MQTT instead."
    elif preferred == "local":
        last_result["hint"] = DEPLOY_HOST_HINT
    return last_result


def _probe_once(client: BambuMqttClient, mode: str, timeout: float) -> dict[str, Any]:
    if mode == "cloud":
        return _probe_cloud(client, timeout)
    return _probe_local(client, timeout)


def _probe_local(client: BambuMqttClient, timeout: float) -> dict[str, Any]:
    ip = client._resolve_ip()
    serial = client._resolve_serial()
    access_code = client._resolve_access_code()
    if not ip or not serial or not access_code:
        return {
            "ok": False,
            "mode": "local",
            "error": "Missing printer IP, serial, or LAN access code.",
        }

    topic_report = f"device/{serial}/report"
    topic_request = f"device/{serial}/request"

    def connect(probe: mqtt.Client) -> None:
        probe.connect(ip, 8883, keepalive=60)

    return _run_probe(
        mode="local",
        target=f"{ip}:8883",
        connect=connect,
        auth=lambda probe: probe.username_pw_set("bblp", access_code),
        topic_report=topic_report,
        topic_request=topic_request,
        timeout=timeout,
    )


def _probe_cloud(client: BambuMqttClient, timeout: float) -> dict[str, Any]:
    cloud = client.cloud
    if not cloud or not cloud.is_configured():
        return {"ok": False, "mode": "cloud", "error": "Cloud credentials are not configured."}

    serial = client._resolve_serial()
    token = cloud._ensure_token()
    user_id = cloud.get_user_id()
    if not serial or not token or user_id is None:
        return {"ok": False, "mode": "cloud", "error": "Cloud MQTT missing serial, token, or user id."}

    broker = cloud.get_mqtt_broker()
    topic_report = f"device/{serial}/report"
    topic_request = f"device/{serial}/request"
    username = f"u_{user_id}"

    def connect(probe: mqtt.Client) -> None:
        probe.connect(broker, 8883, keepalive=60)

    return _run_probe(
        mode="cloud",
        target=broker,
        connect=connect,
        auth=lambda probe: probe.username_pw_set(username, token),
        topic_report=topic_report,
        topic_request=topic_request,
        timeout=timeout,
    )


def _run_probe(
    *,
    mode: str,
    target: str,
    connect,
    auth,
    topic_report: str,
    topic_request: str,
    timeout: float,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "ok": False,
        "mode": mode,
        "target": target,
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
    auth(probe)
    probe.tls_set(cert_reqs=ssl.CERT_NONE)
    probe.tls_insecure_set(True)
    probe.on_connect = on_connect
    probe.on_message = on_message

    try:
        connect(probe)
    except OSError as exc:
        return {**result, "error": f"Could not reach {target} — {exc}", "hint": DEPLOY_HOST_HINT}

    probe.loop_start()
    connect_timeout = min(timeout, 12.0)
    if not connected_event.wait(timeout=connect_timeout):
        probe.loop_stop()
        probe.disconnect()
        return {
            **result,
            "error": f"Timed out connecting to {mode} MQTT at {target}",
            "hint": DEPLOY_HOST_HINT if mode == "local" else None,
        }

    if not trays_event.wait(timeout=max(2.0, timeout - connect_timeout)):
        result["events"].append("no_trays_before_timeout")

    probe.loop_stop()
    probe.disconnect()

    result["ok"] = bool(result["trays"])
    if not result["ok"] and "error" not in result:
        result["error"] = (
            f"Connected via {mode} MQTT but no AMS tray data arrived. "
            "Check AMS is powered and loaded; P1S only sends tray arrays in pushall responses."
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
