"""Publish a database file as a GitHub Release asset via gh CLI.

Intended for local use; GitHub Actions uses softprops/action-gh-release
instead. Requires `gh` CLI installed and authenticated.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, required=True)
    ap.add_argument("--tag", type=str, required=True)
    ap.add_argument("--title", type=str, default=None)
    ap.add_argument("--repo", type=str, default=None)
    ap.add_argument("--notes", type=str, default="")
    ap.add_argument("--draft", action="store_true")
    args = ap.parse_args()

    if not args.db.exists():
        print(f"DB not found: {args.db}", file=sys.stderr)
        return 1

    cmd = [
        "gh", "release", "create", args.tag, str(args.db),
        "--title", args.title or args.tag,
        "--notes", args.notes or f"Automated DB release {args.tag}",
    ]
    if args.repo:
        cmd.extend(["--repo", args.repo])
    if args.draft:
        cmd.append("--draft")

    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"STDOUT:\n{result.stdout}", file=sys.stderr)
        print(f"STDERR:\n{result.stderr}", file=sys.stderr)
        return result.returncode
    print(result.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
