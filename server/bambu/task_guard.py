"""Guardrails for Bambu cloud print import and filament deduction."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from db import connect, get_sync_state, scaled_deduction_g, set_sync_state

AUTO_IMPORT_SOURCES = ("cloud", "mqtt", "ftps")


def cloud_sync_baseline(conn) -> str | None:
    return get_sync_state(conn, "cloud_tasks_after")


def ensure_cloud_sync_baseline(conn) -> str:
    baseline = cloud_sync_baseline(conn)
    if baseline:
        return baseline
    baseline = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    set_sync_state(conn, "cloud_tasks_after", baseline)
    return baseline


def is_bambu_task_ignored(conn, task_id: str | None) -> bool:
    if not task_id:
        return False
    row = conn.execute(
        "SELECT task_id FROM bambu_ignored_tasks WHERE task_id = ?",
        (str(task_id),),
    ).fetchone()
    return row is not None


def ignore_bambu_task(conn, task_id: str | None, reason: str = "") -> None:
    if not task_id:
        return
    conn.execute(
        """
        INSERT INTO bambu_ignored_tasks (task_id, reason)
        VALUES (?, ?)
        ON CONFLICT(task_id) DO NOTHING
        """,
        (str(task_id), reason or None),
    )


def ignore_bambu_tasks(conn, task_ids: list[str], reason: str = "") -> int:
    added = 0
    for task_id in task_ids:
        if not task_id:
            continue
        task_id = str(task_id)
        existing = conn.execute(
            "SELECT task_id FROM bambu_ignored_tasks WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        if existing:
            continue
        ignore_bambu_task(conn, task_id, reason)
        added += 1
    return added


def task_timestamp(task: dict[str, Any]) -> str | None:
    return task.get("endTime") or task.get("startTime") or task.get("ended_at") or task.get("started_at")


def is_before_baseline(conn, timestamp: str | None) -> bool:
    if not timestamp:
        return False
    baseline = cloud_sync_baseline(conn)
    if not baseline:
        return False
    return timestamp < baseline


def should_deduct_auto_import(conn, *, ended_at: str | None, source: str) -> bool:
    if source not in AUTO_IMPORT_SOURCES:
        return True
    if os.environ.get("BAMBU_SYNC_DEDUCT_FILAMENT", "true").lower() in {"0", "false", "no"}:
        return False
    baseline = cloud_sync_baseline(conn)
    if not baseline:
        return False
    if not ended_at:
        return True
    return ended_at >= baseline


def restore_auto_import_deductions(conn) -> tuple[int, float]:
    """Add back filament removed by auto-imported print usages."""
    rows = conn.execute(
        """
        SELECT pu.spool_id, pu.used_g, pj.completion_percent, pj.ended_at, pj.source
        FROM print_usages pu
        JOIN print_jobs pj ON pj.id = pu.print_job_id
        WHERE pj.source IN ('cloud', 'mqtt', 'ftps')
          AND pu.spool_id IS NOT NULL
          AND pu.used_g > 0
        """
    ).fetchall()
    restored_by_spool: dict[int, float] = {}
    for row in rows:
        if not should_deduct_auto_import(conn, ended_at=row["ended_at"], source=row["source"]):
            continue
        grams = scaled_deduction_g(row["used_g"], row["completion_percent"])
        spool_id = int(row["spool_id"])
        restored_by_spool[spool_id] = restored_by_spool.get(spool_id, 0.0) + grams

    for spool_id, grams in restored_by_spool.items():
        conn.execute(
            """
            UPDATE spools
            SET remaining_g = COALESCE(remaining_g, 0) + ?,
                updated_at = datetime('now')
            WHERE id = ?
            """,
            (grams, spool_id),
        )
    return len(restored_by_spool), round(sum(restored_by_spool.values()), 2)


def collect_auto_import_task_ids(conn) -> list[str]:
    rows = conn.execute(
        """
        SELECT bambu_task_id FROM print_jobs
        WHERE source IN ('cloud', 'mqtt', 'ftps') AND bambu_task_id IS NOT NULL
        """
    ).fetchall()
    return [str(row["bambu_task_id"]) for row in rows if row["bambu_task_id"]]
