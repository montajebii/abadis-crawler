"""Merge all CSVs from data/raw/ into a single SQLite database.

This script is idempotent: it always rebuilds the DB from scratch by
reading every CSV and deduplicating on (word_canonical, source_key).
"""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = PROJECT_ROOT / "db" / "schema.sql"
DEFAULT_RAW_DIR = PROJECT_ROOT / "data" / "raw"
DEFAULT_DB_PATH = PROJECT_ROOT / "abadis.db"


def init_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    for p in (db_path, Path(f"{db_path}-wal"), Path(f"{db_path}-shm")):
        if p.exists():
            p.unlink()
    conn = sqlite3.connect(str(db_path), isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        conn.executescript(f.read())
    return conn


def collect_rows(raw_dir: Path) -> list[dict]:
    rows: list[dict] = []
    for csv_path in sorted(raw_dir.glob("*.csv")):
        try:
            with open(csv_path, "r", encoding="utf-8", newline="") as f:
                for r in csv.DictReader(f):
                    r["_src"] = csv_path.name
                    rows.append(r)
        except Exception as e:
            print(f"WARN: skip {csv_path.name}: {e}", file=sys.stderr)
    return rows


def _pick(rows: list[dict], field: str, required: bool) -> Optional[str]:
    for r in rows:
        v = (r.get(field) or "").strip()
        if v:
            return v
    return "" if required else None


def merge_into_db(conn: sqlite3.Connection, rows: list[dict]) -> dict:
    stats = {
        "words_inserted": 0,
        "words_updated": 0,
        "defs_inserted": 0,
        "defs_skipped": 0,
        "total_rows": len(rows),
    }

    by_word: dict[str, list[dict]] = {}
    for r in rows:
        canon = (r.get("word_canonical") or "").strip()
        if not canon:
            continue
        by_word.setdefault(canon, []).append(r)

    conn.execute("BEGIN IMMEDIATE")
    try:
        for canon, word_rows in by_word.items():
            display = _pick(word_rows, "word_display", required=True) or canon
            pron = _pick(word_rows, "word_pronunciation", required=False)
            eng = _pick(word_rows, "word_english_mean", required=False)

            cur = conn.execute(
                "INSERT OR IGNORE INTO words "
                "(canonical, display_form, pronunciation, english_mean) "
                "VALUES (?, ?, ?, ?)",
                (canon, display, pron, eng),
            )
            if cur.rowcount > 0:
                stats["words_inserted"] += 1
                word_id = cur.lastrowid
            else:
                row = conn.execute(
                    "SELECT id, pronunciation, english_mean FROM words "
                    "WHERE canonical=?", (canon,),
                ).fetchone()
                word_id = row["id"]
                new_pron = row["pronunciation"] or pron
                new_eng = row["english_mean"] or eng
                if (new_pron != row["pronunciation"]
                        or new_eng != row["english_mean"]):
                    conn.execute(
                        "UPDATE words SET pronunciation=?, english_mean=? "
                        "WHERE id=?", (new_pron, new_eng, word_id),
                    )
                    stats["words_updated"] += 1

            for r in word_rows:
                source = (r.get("source_key") or "").strip()
                if not source:
                    continue
                cur = conn.execute(
                    "INSERT OR IGNORE INTO definitions "
                    "(word_id, source_key, source_title, content_text) "
                    "VALUES (?, ?, ?, ?)",
                    (
                        word_id,
                        source,
                        (r.get("source_title") or "").strip(),
                        (r.get("definition_text") or "").strip(),
                    ),
                )
                if cur.rowcount > 0:
                    stats["defs_inserted"] += 1
                else:
                    stats["defs_skipped"] += 1

        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    return stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    ap.add_argument("--stats", type=Path, default=None)
    args = ap.parse_args()

    if not args.raw_dir.exists():
        print(f"Raw dir not found: {args.raw_dir}", file=sys.stderr)
        return 1

    csv_count = len(list(args.raw_dir.glob("*.csv")))
    rows = collect_rows(args.raw_dir)
    print(f"Collected {len(rows)} rows from {csv_count} CSV file(s)")

    conn = init_db(args.db)
    try:
        stats = merge_into_db(conn, rows)
    finally:
        conn.close()

    print(f"Words:       {stats['words_inserted']} inserted, "
          f"{stats['words_updated']} updated")
    print(f"Definitions: {stats['defs_inserted']} inserted, "
          f"{stats['defs_skipped']} skipped (duplicate)")
    print(f"Database:    {args.db}")

    if args.stats:
        args.stats.parent.mkdir(parents=True, exist_ok=True)
        args.stats.write_text(json.dumps(stats, indent=2), encoding="utf-8")

    return 0


if __name__ == "__main__":
    sys.exit(main())
