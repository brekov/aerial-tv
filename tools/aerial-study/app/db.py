"""SQLite access layer.

One short-lived connection per operation keeps the service thread-safe without
an ORM.  WAL mode allows the admin UI to read while the ASR/generation threads
write.  Every call goes through :func:`session`, which commits on success and
rolls back on error.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .migrations import migrate_v2, migrate_v4
from .util import iso, json_dumps, safe_json_loads, utcnow

SCHEMA_VERSION = 4


def _connect(settings: Settings) -> sqlite3.Connection:
    conn = sqlite3.connect(
        settings.db_path,
        timeout=15,
        isolation_level=None,  # autocommit; explicit BEGIN in session()
        check_same_thread=False,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 15000")
    return conn


@contextmanager
def session(settings: Settings) -> Iterator[sqlite3.Connection]:
    """Yield a connection inside a write transaction."""
    conn = _connect(settings)
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.execute("COMMIT")
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        raise
    finally:
        conn.close()


@contextmanager
def read_session(settings: Settings) -> Iterator[sqlite3.Connection]:
    """Yield a read-only connection (no explicit transaction needed)."""
    conn = _connect(settings)
    try:
        yield conn
    finally:
        conn.close()


def init_db(settings: Settings) -> None:
    """Create directories and apply the schema.  Safe to run on every start."""
    settings.prepare_dirs()
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    schema_path = Path(__file__).with_name("schema.sql")
    script = schema_path.read_text(encoding="utf-8")
    conn = _connect(settings)
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(script)
        current = conn.execute("PRAGMA user_version").fetchone()[0]
        if current < 2:
            migrate_v2(conn, iso(utcnow()))
        if current < 4:
            migrate_v4(conn)
        if current < SCHEMA_VERSION:
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        conn.commit()
    finally:
        conn.close()


def check_db(settings: Settings) -> bool:
    try:
        with read_session(settings) as conn:
            conn.execute("SELECT 1").fetchone()
        return True
    except sqlite3.Error:
        return False


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def rows_to_dicts(rows: Sequence[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# settings table (non-secret provider overrides only)
# ---------------------------------------------------------------------------


def get_setting(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        """
        INSERT INTO settings(key, value, updated_at) VALUES(?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value,
                                      updated_at = excluded.updated_at
        """,
        (key, value, iso(utcnow())),
    )


def get_json_setting(conn: sqlite3.Connection, key: str, default: Any) -> Any:
    return safe_json_loads(get_setting(conn, key, ""), default)


def set_json_setting(conn: sqlite3.Connection, key: str, value: Any) -> None:
    set_setting(conn, key, json_dumps(value))
