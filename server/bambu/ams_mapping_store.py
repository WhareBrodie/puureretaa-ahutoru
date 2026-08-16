"""Persist AMS tray mapping captured from MQTT for later cloud import."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from db import connect

logger = logging.getLogger("bambu.ams_mapping")


def _normalize_mapping(raw: Any) -> list[int] | None:
    if not isinstance(raw, list) or not raw:
        return None
    if isinstance(raw[0], dict):
        return None
    try:
        values = [int(value) for value in raw]
    except (TypeError, ValueError):
        return None
    return values


def capture_ams_mapping_from_mqtt(print_data: dict[str, Any]) -> list[int] | None:
    """Save ams_mapping from an MQTT print payload when present."""
    mapping = _normalize_mapping(print_data.get("ams_mapping") or print_data.get("amsMapping"))
    if not mapping:
        return None

    task_id = print_data.get("task_id") or print_data.get("subtask_id")
    task_id = str(task_id).strip() if task_id not in (None, "") else None
    gcode_file = print_data.get("gcode_file")
    subtask_name = print_data.get("subtask_name")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = json.dumps(mapping)

    with connect() as conn:
        conn.execute(
            """
            INSERT INTO bambu_active_print_mapping (id, task_id, ams_mapping, gcode_file, subtask_name, updated_at)
            VALUES (1, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
              task_id = excluded.task_id,
              ams_mapping = excluded.ams_mapping,
              gcode_file = excluded.gcode_file,
              subtask_name = excluded.subtask_name,
              updated_at = excluded.updated_at
            """,
            (task_id, payload, gcode_file, subtask_name, now),
        )
        if task_id:
            conn.execute(
                """
                INSERT INTO bambu_print_ams_mapping (task_id, ams_mapping, gcode_file, subtask_name, captured_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                  ams_mapping = excluded.ams_mapping,
                  gcode_file = COALESCE(excluded.gcode_file, bambu_print_ams_mapping.gcode_file),
                  subtask_name = COALESCE(excluded.subtask_name, bambu_print_ams_mapping.subtask_name),
                  captured_at = excluded.captured_at
                """,
                (task_id, payload, gcode_file, subtask_name, now),
            )

    logger.info("Captured MQTT ams_mapping=%s task_id=%s", mapping, task_id or "(active)")
    return mapping


def lookup_ams_mapping(
    *,
    task_id: str | None = None,
    gcode_file: str | None = None,
) -> list[int] | None:
    """Return stored AMS mapping for a cloud/MQTT task if we captured it at print start."""
    with connect() as conn:
        if task_id:
            row = conn.execute(
                "SELECT ams_mapping FROM bambu_print_ams_mapping WHERE task_id = ?",
                (str(task_id),),
            ).fetchone()
            if row:
                try:
                    return [int(value) for value in json.loads(row["ams_mapping"])]
                except (TypeError, ValueError, json.JSONDecodeError):
                    pass

        active = conn.execute(
            "SELECT task_id, ams_mapping, gcode_file FROM bambu_active_print_mapping WHERE id = 1"
        ).fetchone()
        if not active:
            return None
        try:
            mapping = [int(value) for value in json.loads(active["ams_mapping"])]
        except (TypeError, ValueError, json.JSONDecodeError):
            return None

        if task_id and active["task_id"] and str(active["task_id"]) == str(task_id):
            return mapping
        if gcode_file and active["gcode_file"] and str(active["gcode_file"]).lower() in str(gcode_file).lower():
            return mapping
        if task_id and active["task_id"] and str(active["task_id"]) != str(task_id):
            return None
        # Fall back to active mapping only when no conflicting task id is known.
        if not task_id:
            return mapping
    return None
