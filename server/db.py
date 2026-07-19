"""SQLite database helpers for Pūreretā Ahutoru."""

from __future__ import annotations

import json
import math
import os
import re
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

SCHEMA_VERSION = 7


def get_root() -> Path:
    return Path(os.environ.get("PURERETA_ROOT", Path(__file__).resolve().parent.parent))


def get_data_dir(root: Path | None = None) -> Path:
    root = root or get_root()
    data_dir = root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "photos").mkdir(parents=True, exist_ok=True)
    return data_dir


def get_db_path(root: Path | None = None) -> Path:
    return get_data_dir(root) / "purereta.db"


def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [row_to_dict(row) for row in rows]


@contextmanager
def connect(root: Path | None = None) -> Iterator[sqlite3.Connection]:
    db_path = get_db_path(root)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _repair_schema_version_7(conn: sqlite3.Connection) -> None:
    """Migration 007 originally omitted schema_version bump; repair if columns already exist."""
    version_row = conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
    current_version = version_row["v"] if version_row and version_row["v"] is not None else 0
    if current_version >= 7:
        return
    columns = {row[1] for row in conn.execute("PRAGMA table_info(ams_slot_mappings)")}
    if "baseline_tray_info_idx" in columns:
        conn.execute("INSERT INTO schema_version (version) VALUES (7)")


def run_migrations(root: Path | None = None) -> None:
    root = root or get_root()
    migrations_dir = root / "data" / "migrations"
    seed_migrations = root / "_seed" / "migrations"
    if not migrations_dir.is_dir() and seed_migrations.is_dir():
        migrations_dir = seed_migrations

    with connect(root) as conn:
        current = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'").fetchone()
        if current is None:
            for migration_file in sorted(migrations_dir.glob("*.sql")):
                sql = migration_file.read_text(encoding="utf-8")
                conn.executescript(sql)
            return

        _repair_schema_version_7(conn)

        version_row = conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
        current_version = version_row["v"] if version_row else 0
        for migration_file in sorted(migrations_dir.glob("*.sql")):
            match = re.match(r"^(\d+)_", migration_file.name)
            if not match:
                continue
            file_version = int(match.group(1))
            if file_version > current_version:
                conn.executescript(migration_file.read_text(encoding="utf-8"))


def seed_empty_spool_weights(root: Path | None = None) -> None:
    root = root or get_root()
    seed_path = root / "data" / "seed_empty_spool_weights.json"
    if not seed_path.is_file():
        alt = root / "_seed" / "seed_empty_spool_weights.json"
        if alt.is_file():
            seed_path = alt
        else:
            return

    with connect(root) as conn:
        count = conn.execute("SELECT COUNT(*) AS c FROM empty_spool_weights").fetchone()["c"]
        if count > 0:
            return
        entries = json.loads(seed_path.read_text(encoding="utf-8"))
        for entry in entries:
            conn.execute(
                """
                INSERT INTO empty_spool_weights (brand, model, weight_g, notes)
                VALUES (?, ?, ?, ?)
                """,
                (entry["brand"], entry.get("model"), entry["weight_g"], entry.get("notes")),
            )


def init_db(root: Path | None = None) -> None:
    run_migrations(root)
    seed_empty_spool_weights(root)


def get_setting(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        """
        INSERT INTO app_settings (key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (key, value),
    )


def get_sync_state(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM sync_state WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_sync_state(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        """
        INSERT INTO sync_state (key, value, updated_at) VALUES (?, ?, datetime('now'))
        ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = datetime('now')
        """,
        (key, value),
    )


def touch_spool_updated(conn: sqlite3.Connection, spool_id: int) -> None:
    conn.execute(
        "UPDATE spools SET updated_at = datetime('now') WHERE id = ?",
        (spool_id,),
    )


def ceil_usage_g(grams: float) -> float:
    """Round filament usage up to one decimal place (e.g. 11.61 → 11.7)."""
    if grams <= 0:
        return 0.0
    return math.ceil(grams * 10) / 10


def scaled_deduction_g(used_g: float, completion_percent: float | None) -> float:
    scale = max(0.0, min(completion_percent or 100.0, 100.0)) / 100.0
    return ceil_usage_g(float(used_g) * scale)


def deduct_spool_weight(conn: sqlite3.Connection, spool_id: int, grams: float) -> None:
    grams = ceil_usage_g(grams)
    if grams <= 0:
        return
    conn.execute(
        """
        UPDATE spools
        SET remaining_g = MAX(0, COALESCE(remaining_g, 0) - ?),
            updated_at = datetime('now')
        WHERE id = ?
        """,
        (grams, spool_id),
    )
