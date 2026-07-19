"""Project grouping for related print jobs."""

from __future__ import annotations

from typing import Any

from db import connect, row_to_dict
from routes.prints import _attach_usages, _print_query


def _project_cost(conn, project_id: int) -> tuple[float | None, int]:
    rows = conn.execute(
        """
        SELECT pu.used_g, s.purchase_price, s.initial_weight_g
        FROM print_jobs pj
        JOIN print_usages pu ON pu.print_job_id = pj.id
        LEFT JOIN spools s ON s.id = pu.spool_id
        WHERE pj.project_id = ?
        """,
        (project_id,),
    ).fetchall()
    total_cost = 0.0
    has_cost = False
    for row in rows:
        used_g = row["used_g"]
        purchase_price = row["purchase_price"]
        initial_weight_g = row["initial_weight_g"]
        if purchase_price is None or not initial_weight_g or initial_weight_g <= 0 or not used_g:
            continue
        total_cost += used_g * (purchase_price / initial_weight_g)
        has_cost = True
    return (round(total_cost, 2) if has_cost else None, len(rows))


def list_projects() -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT p.*,
                   COUNT(pj.id) AS print_count
            FROM projects p
            LEFT JOIN print_jobs pj ON pj.project_id = p.id
            GROUP BY p.id
            ORDER BY p.name COLLATE NOCASE
            """
        ).fetchall()
        result = []
        for row in rows:
            project = row_to_dict(row)
            total_cost, _ = _project_cost(conn, project["id"])
            project["total_cost"] = total_cost
            result.append(project)
        return result


def get_project(project_id: int) -> dict[str, Any]:
    with connect() as conn:
        row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        if not row:
            raise KeyError("project not found")
        project = row_to_dict(row)
        total_cost, _ = _project_cost(conn, project_id)
        project["total_cost"] = total_cost

        print_rows = conn.execute(
            _print_query("WHERE pj.project_id = ?"),
            (project_id,),
        ).fetchall()
        prints = []
        for print_row in print_rows:
            prints.append(_attach_usages(conn, row_to_dict(print_row)))
        project["prints"] = prints
        project["print_count"] = len(prints)
        return project


def create_project(data: dict[str, Any]) -> dict[str, Any]:
    name = (data.get("name") or "").strip()
    if not name:
        raise ValueError("project name is required")
    with connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO projects (name, notes)
            VALUES (?, ?)
            """,
            (name, data.get("notes")),
        )
        project_id = cur.lastrowid
    return get_project(project_id)


def update_project(project_id: int, data: dict[str, Any]) -> dict[str, Any]:
    with connect() as conn:
        row = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
        if not row:
            raise KeyError("project not found")
        name = data.get("name")
        if name is not None:
            name = name.strip()
            if not name:
                raise ValueError("project name is required")
        notes = data.get("notes")
        conn.execute(
            """
            UPDATE projects
            SET name = COALESCE(?, name),
                notes = COALESCE(?, notes),
                updated_at = datetime('now')
            WHERE id = ?
            """,
            (name, notes, project_id),
        )
    return get_project(project_id)


def delete_project(project_id: int) -> None:
    with connect() as conn:
        row = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
        if not row:
            raise KeyError("project not found")
        conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
