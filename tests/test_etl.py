"""Tests for ETL scripts."""
import csv
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from merge_and_build import init_db, merge_into_db, collect_rows  # noqa: E402
from validate_csv import validate  # noqa: E402


HEADER = [
    "word_canonical", "word_display", "word_pronunciation",
    "word_english_mean", "source_key", "source_title", "definition_text",
]


def _write_csv(path: Path, rows: list[list[str]]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        w.writerows(rows)


def test_validate_ok(tmp_path):
    p = tmp_path / "ok.csv"
    _write_csv(p, [
        ["سلام", "سلام", "salam", "hello", "amid", "فرهنگ عمید", "درود"],
        ["سلام", "سلام", "salam", "hello", "moeen", "فرهنگ معین", "درود"],
    ])
    ok, errs = validate(p)
    assert ok, errs


def test_validate_missing_column(tmp_path):
    p = tmp_path / "bad.csv"
    p.write_text("word_canonical,word_display\nسلام,سلام\n", encoding="utf-8")
    ok, errs = validate(p)
    assert not ok
    assert any("Missing columns" in e for e in errs)


def test_validate_duplicate_key(tmp_path):
    p = tmp_path / "dup.csv"
    _write_csv(p, [
        ["سلام", "سلام", "", "", "amid", "", "x"],
        ["سلام", "سلام", "", "", "amid", "", "y"],
    ])
    ok, errs = validate(p)
    assert not ok
    assert any("duplicate" in e for e in errs)


def test_validate_unknown_source(tmp_path):
    p = tmp_path / "unk.csv"
    _write_csv(p, [["سلام", "سلام", "", "", "bogus", "", "x"]])
    ok, _ = validate(p, strict=True)
    assert not ok
    ok, _ = validate(p, strict=False)
    assert ok


def test_merge_dedupes_across_files(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    _write_csv(raw / "a.csv", [
        ["سلام", "سلام", "salam", "", "amid", "فرهنگ عمید", "درود"],
    ])
    _write_csv(raw / "b.csv", [
        ["سلام", "سلام", "", "hello", "amid", "فرهنگ عمید", "درود"],
        ["کتاب", "کتاب", "", "", "amid", "فرهنگ عمید", "دفتر"],
    ])
    rows = collect_rows(raw)
    conn = init_db(tmp_path / "test.db")
    try:
        stats = merge_into_db(conn, rows)
        assert stats["words_inserted"] == 2
        assert stats["defs_inserted"] == 2
        assert stats["defs_skipped"] == 1
        # Metadata merged across files
        row = conn.execute(
            "SELECT pronunciation, english_mean FROM words WHERE canonical='سلام'"
        ).fetchone()
        assert row["pronunciation"] == "salam"
        assert row["english_mean"] == "hello"
    finally:
        conn.close()


def test_merge_is_idempotent(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    _write_csv(raw / "a.csv", [
        ["سلام", "سلام", "", "", "amid", "", "x"],
    ])
    rows = collect_rows(raw)
    conn = init_db(tmp_path / "test.db")
    try:
        s1 = merge_into_db(conn, rows)
        s2 = merge_into_db(conn, rows)
        assert s1["words_inserted"] == 1
        assert s1["defs_inserted"] == 1
        assert s2["words_inserted"] == 0
        assert s2["defs_inserted"] == 0
    finally:
        conn.close()
