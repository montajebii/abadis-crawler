"""Validate a single CSV file against the expected schema."""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

REQUIRED_COLUMNS = [
    "word_canonical",
    "word_display",
    "word_pronunciation",
    "word_english_mean",
    "source_key",
    "source_title",
    "definition_text",
]

VALID_SOURCE_KEYS = {
    "dehkhoda", "moeen", "amid", "parsi", "farhang", "idiom",
    "wikiislamic", "wiki", "wikifree", "wikiuser", "name",
    "proverb", "crossword", "wikiquote", "english",
}


def validate(path: Path, strict: bool = True) -> tuple[bool, list[str]]:
    errors: list[str] = []
    if not path.exists():
        return False, [f"File not found: {path}"]

    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            return False, ["Empty CSV or no header"]

        missing = [c for c in REQUIRED_COLUMNS if c not in reader.fieldnames]
        if missing:
            return False, [f"Missing columns: {missing}"]

        seen: set[tuple[str, str]] = set()
        row_count = 0
        for i, row in enumerate(reader, start=2):
            row_count += 1
            canon = (row.get("word_canonical") or "").strip()
            source = (row.get("source_key") or "").strip()
            if not canon:
                errors.append(f"Line {i}: empty word_canonical")
                continue
            if not source:
                errors.append(f"Line {i}: empty source_key")
                continue
            if strict and source not in VALID_SOURCE_KEYS:
                errors.append(f"Line {i}: unknown source_key '{source}'")
            key = (canon, source)
            if key in seen:
                errors.append(f"Line {i}: duplicate key {key}")
            seen.add(key)

        if row_count == 0:
            errors.append("CSV has no data rows")

    return len(errors) == 0, errors


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv_path", type=Path)
    ap.add_argument("--no-strict", action="store_true",
                    help="Allow unknown source_key values")
    args = ap.parse_args()

    ok, errors = validate(args.csv_path, strict=not args.no_strict)
    if ok:
        print(f"OK: {args.csv_path}")
        return 0

    print(f"FAIL: {args.csv_path}")
    for e in errors[:20]:
        print(f"  - {e}")
    if len(errors) > 20:
        print(f"  ... and {len(errors) - 20} more")
    return 1


if __name__ == "__main__":
    sys.exit(main())
