"""Report crawl coverage from a SQLite database."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path


def build_report(db_path: Path) -> dict:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    per_letter = {
        r["letter"]: r["cnt"]
        for r in conn.execute(
            "SELECT substr(canonical,1,1) AS letter, COUNT(*) AS cnt "
            "FROM words GROUP BY letter ORDER BY letter"
        ).fetchall()
    }
    per_source = {
        r["source_key"]: r["cnt"]
        for r in conn.execute(
            "SELECT source_key, COUNT(*) AS cnt "
            "FROM definitions GROUP BY source_key ORDER BY cnt DESC"
        ).fetchall()
    }
    total_words = conn.execute("SELECT COUNT(*) FROM words").fetchone()[0]
    total_defs = conn.execute("SELECT COUNT(*) FROM definitions").fetchone()[0]
    conn.close()

    return {
        "total_words": total_words,
        "total_definitions": total_defs,
        "per_letter": per_letter,
        "per_source": per_source,
    }


def print_report(report: dict) -> None:
    print(f"Total words: {report['total_words']}")
    print(f"Total definitions: {report['total_definitions']}")
    print()
    print("Coverage per letter (least covered first):")
    sorted_letters = sorted(report["per_letter"].items(), key=lambda kv: kv[1])
    for letter, cnt in sorted_letters:
        print(f"  {letter}: {cnt}")
    print()
    print("Definitions per source:")
    for src, cnt in report["per_source"].items():
        print(f"  {src}: {cnt}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=Path("abadis.db"))
    ap.add_argument("--json", type=Path, default=None,
                    help="Write JSON report to this path")
    args = ap.parse_args()

    if not args.db.exists():
        print(f"DB not found: {args.db}", file=sys.stderr)
        return 1

    report = build_report(args.db)
    print_report(report)

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\nWrote {args.json}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
