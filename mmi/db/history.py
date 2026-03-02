"""
history.py — SQLite WAL persistence for MMI download history.

Table: download_history
  - download_status (not 'status') — globally unique field name per project rules
"""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from mmi.config import MMI_DB_PATH, get_logger

logger = get_logger("mmi.db")

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS download_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    url             TEXT NOT NULL,
    download_status TEXT NOT NULL DEFAULT 'pending',
    worker_name     TEXT,
    filename        TEXT,
    timestamp       TEXT NOT NULL,
    error_message   TEXT
);
"""


def _connect(db_path: Path = MMI_DB_PATH) -> sqlite3.Connection:
    """Open (or create) the history DB with WAL mode enabled."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute(_CREATE_TABLE)
    conn.commit()
    return conn


def record_download(
    url: str,
    download_status: str,
    worker_name: str | None = None,
    filename: str | None = None,
    error_message: str | None = None,
    db_path: Path = MMI_DB_PATH,
) -> int:
    """Insert a completed (or failed) download record. Returns the new row id."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    with _connect(db_path) as conn:
        cur = conn.execute(
            """INSERT INTO download_history
               (url, download_status, worker_name, filename, timestamp, error_message)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (url, download_status, worker_name, filename, ts, error_message),
        )
        conn.commit()
        return cur.lastrowid


def get_recent(limit: int = 20, db_path: Path = MMI_DB_PATH) -> list[dict]:
    """Return the most recent `limit` download records as plain dicts."""
    with _connect(db_path) as conn:
        rows = conn.execute(
            """SELECT id, url, download_status, worker_name, filename, timestamp, error_message
               FROM download_history
               ORDER BY id DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]
