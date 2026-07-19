"""SQLite database helpers for Pūreretā Ahutoru."""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

SCHEMA_VERSION = 1


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


def deduct_spool_weight(conn: sqlite3.Connection, spool_id: int, grams: float) -> None:
    conn.execute(
        """
        UPDATE spools
        SET remaining_g = MAX(0, COALESCE(remaining_g, 0) - ?),
            updated_at = datetime('now')
        WHERE id = ?
        """,
        (grams, spool_id),
    )
