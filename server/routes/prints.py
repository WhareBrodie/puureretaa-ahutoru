"""Print job logging and review queue."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from db import connect, ceil_usage_g, deduct_spool_weight, row_to_dict, rows_to_dicts, scaled_deduction_g


def _print_query(where: str = "", params: tuple[Any, ...] = ()) -> str:
    return f"""
        SELECT pj.*, p.name AS printer_name, pr.name AS project_name
        FROM print_jobs pj
        LEFT JOIN printers p ON p.id = pj.printer_id
        LEFT JOIN projects pr ON pr.id = pj.project_id
        {where}
        ORDER BY COALESCE(pj.started_at, pj.created_at) DESC
    """


def _usage_cost(used_g: float | None, purchase_price: float | None, initial_weight_g: float | None) -> float | None:
    if purchase_price is None or not initial_weight_g or initial_weight_g <= 0 or not used_g:
        return None
    return round(used_g * (purchase_price / initial_weight_g), 2)


def _attach_usages(conn, print_job: dict[str, Any]) -> dict[str, Any]:
    usages = conn.execute(
        """
        SELECT pu.*, s.purchase_price, s.initial_weight_g, s.brand, s.color_name
        FROM print_usages pu
        LEFT JOIN spools s ON s.id = pu.spool_id
        WHERE pu.print_job_id = ?
        ORDER BY pu.ams_slot
        """,
        (print_job["id"],),
    ).fetchall()
    usage_dicts = rows_to_dicts(usages)
    total_cost = 0.0
    has_cost = False
    for usage in usage_dicts:
        cost = _usage_cost(usage.get("used_g"), usage.get("purchase_price"), usage.get("initial_weight_g"))
        usage["cost"] = cost
        if cost is not None:
            total_cost += cost
            has_cost = True
    print_job["usages"] = usage_dicts
    print_job["total_cost"] = round(total_cost, 2) if has_cost else None
    return print_job


def list_prints(pending_review_only: bool = False) -> list[dict[str, Any]]:
    where = "WHERE pj.needs_review = 1" if pending_review_only else ""
    with connect() as conn:
        rows = conn.execute(_print_query(where)).fetchall()
        result = []
        for row in rows:
            item = _attach_usages(conn, row_to_dict(row))
            result.append(item)
        return result


def get_print(print_id: int) -> dict[str, Any]:
    with connect() as conn:
        row = conn.execute(
            _print_query("WHERE pj.id = ?"),
            (print_id,),
        ).fetchone()
        if not row:
            raise KeyError("print not found")
        return _attach_usages(conn, row_to_dict(row))


def create_manual_print(data: dict[str, Any]) -> dict[str, Any]:
    title = (data.get("title") or "Manual print").strip()
    started_at = data.get("started_at") or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    usages = data.get("usages") or []
    if not usages:
        raise ValueError("at least one usage entry is required")

    with connect() as conn:
        total_used = sum(float(u.get("used_g") or 0) for u in usages)
        duration_s = data.get("duration_s")
        cur = conn.execute(
            """
            INSERT INTO print_jobs (
                title, started_at, ended_at, duration_s, status, source, printer_id,
                needs_review, total_used_g, completion_percent, project_id
            ) VALUES (?, ?, ?, ?, 'completed', 'manual', ?, 0, ?, 100, ?)
            """,
            (
                title,
                started_at,
                data.get("ended_at") or started_at,
                duration_s,
                data.get("printer_id") or 1,
                total_used,
                data.get("project_id"),
            ),
        )
        print_id = cur.lastrowid
        for usage in usages:
            spool_id = usage.get("spool_id")
            used_g = ceil_usage_g(float(usage.get("used_g") or 0))
            conn.execute(
                """
                INSERT INTO print_usages (
                    print_job_id, ams_slot, spool_id, material, color, used_g, used_m, resolved
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    print_id,
                    usage.get("ams_slot"),
                    spool_id,
                    usage.get("material"),
                    usage.get("color"),
                    used_g,
                    usage.get("used_m"),
                    1 if spool_id else 0,
                ),
            )
            if spool_id and used_g > 0:
                deduct_spool_weight(conn, spool_id, used_g)
    return get_print(print_id)


def update_print(print_id: int, data: dict[str, Any]) -> dict[str, Any]:
    with connect() as conn:
        row = conn.execute("SELECT id FROM print_jobs WHERE id = ?", (print_id,)).fetchone()
        if not row:
            raise KeyError("print not found")

        updates: list[str] = []
        params: list[Any] = []

        if "title" in data:
            title = (data.get("title") or "").strip()
            if not title:
                raise ValueError("print title is required")
            updates.append("title = ?")
            params.append(title)

        if "project_id" in data:
            project_id = data.get("project_id")
            if project_id in (None, "", 0, "0"):
                project_id = None
            else:
                project_id = int(project_id)
                exists = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
                if not exists:
                    raise ValueError("project not found")
            updates.append("project_id = ?")
            params.append(project_id)

        if not updates:
            return get_print(print_id)

        params.append(print_id)
        conn.execute(
            f"UPDATE print_jobs SET {', '.join(updates)} WHERE id = ?",
            tuple(params),
        )
    return get_print(print_id)


def resolve_print_review(print_id: int, assignments: list[dict[str, Any]], skip_deduction: bool = False) -> dict[str, Any]:
    with connect() as conn:
        job = conn.execute("SELECT * FROM print_jobs WHERE id = ?", (print_id,)).fetchone()
        if not job:
            raise KeyError("print not found")
        if not job["needs_review"]:
            raise ValueError("print is not pending review")

        for assignment in assignments:
            usage_id = assignment.get("usage_id")
            spool_id = assignment.get("spool_id")
            if not usage_id:
                continue
            usage = conn.execute(
                "SELECT * FROM print_usages WHERE id = ? AND print_job_id = ?",
                (usage_id, print_id),
            ).fetchone()
            if not usage:
                raise KeyError(f"usage {usage_id} not found")
            conn.execute(
                "UPDATE print_usages SET spool_id = ?, resolved = ? WHERE id = ?",
                (spool_id, 1 if spool_id else 0, usage_id),
            )
            if spool_id and not skip_deduction and usage["used_g"] > 0:
                deduct_spool_weight(
                    conn,
                    spool_id,
                    scaled_deduction_g(usage["used_g"], job["completion_percent"]),
                )

        unresolved = conn.execute(
            "SELECT COUNT(*) AS c FROM print_usages WHERE print_job_id = ? AND (spool_id IS NULL OR resolved = 0)",
            (print_id,),
        ).fetchone()["c"]
        conn.execute(
            """
            UPDATE print_jobs
            SET needs_review = ?, review_note = ?
            WHERE id = ?
            """,
            (1 if unresolved else 0, assignment.get("review_note") if isinstance(assignment, dict) else None, print_id),
        )
    return get_print(print_id)


def resolve_print_review_v2(print_id: int, data: dict[str, Any]) -> dict[str, Any]:
    assignments = data.get("assignments") or []
    skip = bool(data.get("skip_deduction"))
    with connect() as conn:
        job = conn.execute("SELECT * FROM print_jobs WHERE id = ?", (print_id,)).fetchone()
        if not job:
            raise KeyError("print not found")

        for assignment in assignments:
            usage_id = assignment.get("usage_id")
            spool_id = assignment.get("spool_id")
            usage = conn.execute(
                "SELECT * FROM print_usages WHERE id = ? AND print_job_id = ?",
                (usage_id, print_id),
            ).fetchone()
            if not usage:
                continue
            conn.execute(
                "UPDATE print_usages SET spool_id = ?, resolved = ? WHERE id = ?",
                (spool_id, 1 if spool_id else 0, usage_id),
            )
            if spool_id and not skip and usage["used_g"] > 0:
                deduct_spool_weight(
                    conn,
                    spool_id,
                    scaled_deduction_g(usage["used_g"], job["completion_percent"]),
                )

        unresolved = conn.execute(
            "SELECT COUNT(*) AS c FROM print_usages WHERE print_job_id = ? AND spool_id IS NULL",
            (print_id,),
        ).fetchone()["c"]
        conn.execute(
            """
            UPDATE print_jobs SET needs_review = ?, review_note = ? WHERE id = ?
            """,
            (1 if unresolved else 0, data.get("review_note"), print_id),
        )
    return get_print(print_id)


def delete_print(print_id: int, restore_weight: bool = True) -> dict[str, Any]:
    with connect() as conn:
        job = conn.execute("SELECT * FROM print_jobs WHERE id = ?", (print_id,)).fetchone()
        if not job:
            raise KeyError("print not found")

        restored_g = 0.0
        if restore_weight:
            usages = conn.execute(
                "SELECT * FROM print_usages WHERE print_job_id = ?",
                (print_id,),
            ).fetchall()
            for usage in usages:
                if not usage["spool_id"] or usage["used_g"] <= 0:
                    continue
                grams = scaled_deduction_g(usage["used_g"], job["completion_percent"])
                conn.execute(
                    """
                    UPDATE spools
                    SET remaining_g = COALESCE(remaining_g, 0) + ?,
                        updated_at = datetime('now')
                    WHERE id = ?
                    """,
                    (grams, usage["spool_id"]),
                )
                restored_g += grams

        conn.execute("DELETE FROM print_jobs WHERE id = ?", (print_id,))

    return {"ok": True, "restored_g": round(restored_g, 2)}
