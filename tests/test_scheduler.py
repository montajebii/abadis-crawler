"""Tests for crawler.scheduler helpers."""
import sqlite3
from pathlib import Path

from crawler.db import init_schema
from crawler.scheduler import (
    _count_pending,
    _insert_word_href,
    _pop_pending,
)


SCHEMA = Path(__file__).parent.parent / "db" / "schema.sql"


def _mem_conn():
    # isolation_level=None matches crawler.db.connect() (autocommit mode)
    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    init_schema(conn, SCHEMA)
    return conn


def test_insert_word_href_dedupes():
    conn = _mem_conn()
    conn.execute("BEGIN")
    _insert_word_href(conn, "/fatofa/سلام/")
    _insert_word_href(conn, "/fatofa/کتاب/")
    _insert_word_href(conn, "/fatofa/سلام/")  # duplicate
    conn.execute("COMMIT")
    assert _count_pending(conn) == 2


def test_insert_word_href_normalizes():
    conn = _mem_conn()
    conn.execute("BEGIN")
    # Arabic yeh vs Persian yeh should normalize to same
    _insert_word_href(conn, "/fatofa/علي/")
    _insert_word_href(conn, "/fatofa/علی/")
    conn.execute("COMMIT")
    assert _count_pending(conn) == 1


def test_insert_word_href_skips_invalid():
    conn = _mem_conn()
    conn.execute("BEGIN")
    _insert_word_href(conn, "")
    _insert_word_href(conn, "/single/")
    conn.execute("COMMIT")
    assert _count_pending(conn) == 0


def test_pop_pending_excludes():
    conn = _mem_conn()
    conn.execute("BEGIN")
    _insert_word_href(conn, "/fatofa/سلام/")
    _insert_word_href(conn, "/fatofa/کتاب/")
    conn.execute("COMMIT")

    row1 = _pop_pending(conn)
    assert row1 is not None
    word1_id = row1["word_id"]

    row2 = _pop_pending(conn, exclude={word1_id})
    assert row2 is not None
    assert row2["word_id"] != word1_id

    row3 = _pop_pending(conn, exclude={word1_id, row2["word_id"]})
    assert row3 is None
