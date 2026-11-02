"""SQLite helpers: connection, schema init, transactions, CRUD."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Optional


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def init_schema(conn: sqlite3.Connection, schema_path: Path) -> None:
    with open(schema_path, "r", encoding="utf-8") as f:
        conn.executescript(f.read())
    _migrate(conn)


def _migrate(conn: sqlite3.Connection) -> None:
    """Idempotent schema migrations for existing DBs."""
    migrations = [
        # 2026-11-02: track "0-word suspicion" per page so a transient
        # block (empty 200 OK with no title) isn't mistaken for end-of-letter
        "ALTER TABLE crawl_pages ADD COLUMN empty_retries INTEGER NOT NULL DEFAULT 0",
    ]
    for sql in migrations:
        try:
            conn.execute(sql)
        except sqlite3.OperationalError:
            pass  # column already exists


@contextmanager
def transaction(conn: sqlite3.Connection):
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def ensure_dictionary(
    conn: sqlite3.Connection,
    slug: str,
    base_url: str,
    display_name: Optional[str] = None,
) -> int:
    row = conn.execute(
        "SELECT id FROM dictionaries WHERE slug = ?", (slug,)
    ).fetchone()
    if row:
        return row["id"]
    cur = conn.execute(
        "INSERT INTO dictionaries (slug, base_url, display_name) VALUES (?, ?, ?)",
        (slug, base_url, display_name),
    )
    return cur.lastrowid


def get_or_create_word(
    conn: sqlite3.Connection,
    canonical: str,
    display_form: str,
    pronunciation: Optional[str] = None,
    english_mean: Optional[str] = None,
) -> int:
    row = conn.execute(
        "SELECT id FROM words WHERE canonical = ?", (canonical,)
    ).fetchone()
    if row:
        return row["id"]
    cur = conn.execute(
        "INSERT INTO words (canonical, display_form, pronunciation, english_mean) "
        "VALUES (?, ?, ?, ?)",
        (canonical, display_form, pronunciation, english_mean),
    )
    return cur.lastrowid


def insert_definition(
    conn: sqlite3.Connection,
    word_id: int,
    source_key: str,
    source_title: str,
    content_text: str,
) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO definitions "
        "(word_id, source_key, source_title, content_text) VALUES (?, ?, ?, ?)",
        (word_id, source_key, source_title, content_text),
    )


def word_is_done(conn: sqlite3.Connection, word_id: int) -> bool:
    row = conn.execute(
        "SELECT status FROM word_queue WHERE word_id = ?", (word_id,)
    ).fetchone()
    return row is not None and row["status"] == "done"


def mark_word(
    conn: sqlite3.Connection,
    word_id: int,
    status: str,
    error: Optional[str] = None,
) -> None:
    conn.execute(
        "INSERT INTO word_queue (word_id, status, last_error, updated_at) "
        "VALUES (?, ?, ?, datetime('now')) "
        "ON CONFLICT(word_id) DO UPDATE SET "
        "status = excluded.status, "
        "last_error = excluded.last_error, "
        "attempts = attempts + 1, "
        "updated_at = excluded.updated_at",
        (word_id, status, error),
    )
