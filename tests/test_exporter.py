"""Tests for crawler.exporter."""
import sqlite3
from pathlib import Path

from crawler.db import (
    get_or_create_word,
    init_schema,
    insert_definition,
    mark_word,
)
from crawler.exporter import CSV_COLUMNS, export_csv


SCHEMA = Path(__file__).parent.parent / "db" / "schema.sql"


def _seed_conn():
    # isolation_level=None matches crawler.db.connect() (autocommit mode)
    # so the pending inserts don't leave an open transaction that would
    # conflict with export_csv's explicit BEGIN IMMEDIATE.
    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    init_schema(conn, SCHEMA)

    wid = get_or_create_word(conn, "سلام", "سلام", "salam", "hello")
    insert_definition(conn, wid, "amid", "فرهنگ عمید", "درود")
    insert_definition(conn, wid, "moeen", "فرهنگ معین", "درود گفتن")
    mark_word(conn, wid, "done")
    return conn


def test_export_writes_header_and_rows(tmp_path):
    conn = _seed_conn()
    out = tmp_path / "out.csv"
    count = export_csv(conn, out)
    assert count == 2

    text = out.read_text(encoding="utf-8")
    header = text.splitlines()[0]
    for col in CSV_COLUMNS:
        assert col in header
    assert "سلام" in text
    assert "فرهنگ عمید" in text
    assert "فرهنگ معین" in text


def test_export_only_new_data(tmp_path):
    conn = _seed_conn()
    out1 = tmp_path / "out1.csv"
    first = export_csv(conn, out1)
    assert first == 2

    out2 = tmp_path / "out2.csv"
    second = export_csv(conn, out2)
    assert second == 0
