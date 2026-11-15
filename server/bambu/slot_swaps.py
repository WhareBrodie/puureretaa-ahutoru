"""Track mid-print AMS spool swaps for review-first filament splits."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from db import get_sync_state

logger = logging.getLogger("bambu.slot_swaps")

SOURCE_RFID = "rfid_mismatch"
SOURCE_REMAP = "manual_remap"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def active_print_context(conn) -> dict[str, Any] | None:
    """Return active task_id / mc_percent when printer is RUNNING or PAUSE."""
    state_raw = get_sync_state(conn, "live_printer_state")
    if not state_raw:
        return None
    try:
        state = json.loads(state_raw)
    except json.JSONDecodeError:
        return None
    gcode_state = str(state.get("gcode_state") or "").upper()
    if gcode_state not in {"RUNNING", "PAUSE"}:
        return None
    task_id = state.get("task_id")
    if task_id is None or str(task_id).strip() == "":
        # Fall back to MQTT-captured active mapping row.
        active = conn.execute(
            "SELECT task_id FROM bambu_active_print_mapping WHERE id = 1"
        ).fetchone()
        if not active or not active["task_id"]:
            return None
        task_id = active["task_id"]
    mc = state.get("mc_percent")
    try:
        mc_percent = float(mc) if mc is not None else None
    except (TypeError, ValueError):
        mc_percent = None
    return {"task_id": str(task_id), "mc_percent": mc_percent, "gcode_state": gcode_state}


def _spool_remaining(conn, spool_id: int | None) -> float | None:
    if not spool_id:
        return None
    row = conn.execute(
        "SELECT remaining_g FROM spools WHERE id = ?",
        (spool_id,),
    ).fetchone()
    if not row or row["remaining_g"] is None:
        return None
    return float(row["remaining_g"])


def get_open_swap(conn, task_id: str, ams_slot: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT * FROM bambu_print_slot_swaps
        WHERE task_id = ? AND ams_slot = ? AND consumed_at IS NULL
        """,
        (task_id, ams_slot),
    ).fetchone()
    return dict(row) if row else None


def lookup_swap_for_import(conn, task_id: str, ams_slot: int) -> dict[str, Any] | None:
    """Prefer an unconsumed swap; fall back to most recent for this task/slot."""
    open_swap = get_open_swap(conn, task_id, ams_slot)
    if open_swap:
        return open_swap
    row = conn.execute(
        """
        SELECT * FROM bambu_print_slot_swaps
        WHERE task_id = ? AND ams_slot = ?
        ORDER BY detected_at DESC
        LIMIT 1
        """,
        (task_id, ams_slot),
    ).fetchone()
    return dict(row) if row else None


def open_or_update_rfid_swap(
    conn,
    *,
    task_id: str,
    ams_slot: int,
    old_spool_id: int | None,
    mc_percent: float | None = None,
) -> dict[str, Any] | None:
    """Open a swap on RFID mismatch. Never overwrite an existing snapshot."""
    existing = get_open_swap(conn, task_id, ams_slot)
    if existing:
        return existing
    # UNIQUE(task_id, ams_slot) — do not reopen after the print already consumed the swap.
    prior = conn.execute(
        """
        SELECT id FROM bambu_print_slot_swaps
        WHERE task_id = ? AND ams_slot = ?
        """,
        (task_id, ams_slot),
    ).fetchone()
    if prior:
        return None
    remaining = _spool_remaining(conn, old_spool_id)
    conn.execute(
        """
        INSERT INTO bambu_print_slot_swaps (
            task_id, ams_slot, old_spool_id, old_remaining_g, mc_percent_at_detect,
            source, detected_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (task_id, ams_slot, old_spool_id, remaining, mc_percent, SOURCE_RFID, _now()),
    )
    logger.info(
        "Opened RFID mid-print swap task=%s slot=%s old_spool=%s remaining=%s",
        task_id,
        ams_slot,
        old_spool_id,
        remaining,
    )
    return get_open_swap(conn, task_id, ams_slot)


def record_manual_remap_swap(
    conn,
    *,
    task_id: str,
    ams_slot: int,
    old_spool_id: int | None,
    new_spool_id: int | None,
    mc_percent: float | None = None,
) -> dict[str, Any] | None:
    """Open or update a swap when the user remaps an AMS slot during a print."""
    if new_spool_id and old_spool_id and int(new_spool_id) == int(old_spool_id):
        return get_open_swap(conn, task_id, ams_slot)

    existing = get_open_swap(conn, task_id, ams_slot)
    now = _now()
    if existing:
        remaining = existing.get("old_remaining_g")
        if remaining is None and old_spool_id:
            remaining = _spool_remaining(conn, old_spool_id)
        conn.execute(
            """
            UPDATE bambu_print_slot_swaps
            SET new_spool_id = ?,
                remapped_at = ?,
                old_spool_id = COALESCE(old_spool_id, ?),
                old_remaining_g = COALESCE(old_remaining_g, ?)
            WHERE id = ?
            """,
            (new_spool_id, now, old_spool_id, remaining, existing["id"]),
        )
        logger.info(
            "Updated mid-print swap remap task=%s slot=%s new_spool=%s",
            task_id,
            ams_slot,
            new_spool_id,
        )
        return get_open_swap(conn, task_id, ams_slot)

    prior = conn.execute(
        """
        SELECT id, consumed_at FROM bambu_print_slot_swaps
        WHERE task_id = ? AND ams_slot = ?
        """,
        (task_id, ams_slot),
    ).fetchone()
    if prior:
        # Already consumed by import — ignore late remaps for this task.
        return None

    remaining = _spool_remaining(conn, old_spool_id)
    conn.execute(
        """
        INSERT INTO bambu_print_slot_swaps (
            task_id, ams_slot, old_spool_id, new_spool_id, old_remaining_g,
            mc_percent_at_detect, source, detected_at, remapped_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            task_id,
            ams_slot,
            old_spool_id,
            new_spool_id,
            remaining,
            mc_percent,
            SOURCE_REMAP,
            now,
            now,
        ),
    )
    logger.info(
        "Opened remap mid-print swap task=%s slot=%s old=%s new=%s remaining=%s",
        task_id,
        ams_slot,
        old_spool_id,
        new_spool_id,
        remaining,
    )
    return get_open_swap(conn, task_id, ams_slot)


def mark_swap_consumed(conn, swap_id: int) -> None:
    conn.execute(
        """
        UPDATE bambu_print_slot_swaps
        SET consumed_at = ?
        WHERE id = ? AND consumed_at IS NULL
        """,
        (_now(), swap_id),
    )


def suggest_split_grams(total_used_g: float, old_remaining_g: float | None) -> tuple[float, float]:
    """Suggest old/new grams. Editable starting point only."""
    from db import ceil_usage_g

    total = ceil_usage_g(float(total_used_g or 0))
    if total <= 0:
        return 0.0, 0.0
    if old_remaining_g is None:
        # No inventory hint — put everything on old for review editing.
        return total, 0.0
    old_g = ceil_usage_g(min(max(0.0, float(old_remaining_g)), total))
    new_g = round(max(0.0, total - old_g), 1)
    return old_g, new_g


def _normalize_tray_color(value: str | None) -> str | None:
    if not value:
        return None
    raw = str(value).strip().lstrip("#")[:6]
    if len(raw) != 6:
        return None
    try:
        int(raw, 16)
    except ValueError:
        return None
    return raw.upper()


def _color_distance(hex_a: str | None, hex_b: str | None) -> int:
    if not hex_a or not hex_b:
        return 999
    try:
        ar, ag, ab = int(hex_a[0:2], 16), int(hex_a[2:4], 16), int(hex_a[4:6], 16)
        br, bg, bb = int(hex_b[0:2], 16), int(hex_b[2:4], 16), int(hex_b[4:6], 16)
        return abs(ar - br) + abs(ag - bg) + abs(ab - bb)
    except ValueError:
        return 999


def tray_mismatches_baseline(mapping: dict[str, Any], tray: dict[str, Any]) -> bool:
    """Same rules as AMS mapping_status mismatch (RFID / type / colour)."""
    tray_type = (tray.get("tray_type") or "").strip().upper()
    tray_color = _normalize_tray_color(tray.get("tray_color"))
    tray_info_idx = (tray.get("tray_info_idx") or "").strip()

    baseline_idx = (mapping.get("baseline_tray_info_idx") or "").strip()
    baseline_type = (mapping.get("baseline_tray_type") or "").strip().upper()
    baseline_color = _normalize_tray_color(mapping.get("baseline_tray_color"))

    has_tray_signal = bool(
        tray_type or tray_color or tray_info_idx or tray.get("tag_uid")
    )
    if not has_tray_signal or (not baseline_idx and not baseline_type and not baseline_color):
        return False

    if baseline_idx and tray_info_idx and baseline_idx != tray_info_idx:
        return True
    if baseline_type and tray_type and baseline_type != tray_type:
        return True
    if baseline_color and tray_color and _color_distance(baseline_color, tray_color) > 120:
        return True
    return False


def detect_rfid_swaps_from_trays(
    conn,
    *,
    printer_id: int,
    trays: dict[str, Any],
    printer_state: dict[str, Any] | None = None,
) -> int:
    """Open pending swaps for mapped slots whose live tray diverges during a print."""
    ctx = None
    if printer_state:
        gcode_state = str(printer_state.get("gcode_state") or "").upper()
        if gcode_state in {"RUNNING", "PAUSE"}:
            task_id = printer_state.get("task_id")
            if not task_id:
                active = conn.execute(
                    "SELECT task_id FROM bambu_active_print_mapping WHERE id = 1"
                ).fetchone()
                task_id = active["task_id"] if active else None
            if task_id:
                mc = printer_state.get("mc_percent")
                try:
                    mc_percent = float(mc) if mc is not None else None
                except (TypeError, ValueError):
                    mc_percent = None
                ctx = {"task_id": str(task_id), "mc_percent": mc_percent}
    if not ctx:
        ctx = active_print_context(conn)
    if not ctx:
        return 0

    opened = 0
    for slot_str, tray in trays.items():
        try:
            slot = int(slot_str)
        except (TypeError, ValueError):
            continue
        mapping = conn.execute(
            """
            SELECT spool_id, baseline_tray_info_idx, baseline_tray_type, baseline_tray_color
            FROM ams_slot_mappings
            WHERE printer_id = ? AND slot = ?
            """,
            (printer_id, slot),
        ).fetchone()
        if not mapping or not mapping["spool_id"]:
            continue
        if not tray_mismatches_baseline(dict(mapping), tray or {}):
            continue
        before = get_open_swap(conn, ctx["task_id"], slot)
        open_or_update_rfid_swap(
            conn,
            task_id=ctx["task_id"],
            ams_slot=slot,
            old_spool_id=int(mapping["spool_id"]),
            mc_percent=ctx.get("mc_percent"),
        )
        after = get_open_swap(conn, ctx["task_id"], slot)
        if after and (not before or before["id"] != after["id"]):
            opened += 1
    return opened
