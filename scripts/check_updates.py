"""Daily check: new dictionaries + sentinel fingerprint changes."""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from crawler.discovery import parse_footerlinks
from crawler.fingerprint import compute_fingerprint, sentinel_pages
from crawler.discovery import parse_word_list_page


UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36"


def fetch(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("data/updates.json"))
    ap.add_argument("--sample-dict", default="dehkhoda")
    ap.add_argument("--sample-letters", nargs="+", default=["ا", "ر", "ک"])
    args = ap.parse_args()

    report = {
        "dictionaries": {"current": [], "added": [], "removed": []},
        "samples": [],
        "detected_updates": False,
    }

    # ── 1) New / removed dictionaries ─────────────────────────
    try:
        html = fetch("https://abadis.ir/footerlinks/")
        current = sorted({link["slug"] for link in parse_footerlinks(html)})
        report["dictionaries"]["current"] = current

        config = json.loads(
            Path("config/dictionaries.json").read_text(encoding="utf-8")
        )
        configured = {d["slug"] for d in config["dictionaries"]}

        added = sorted(set(current) - configured)
        removed = sorted(configured - set(current))
        report["dictionaries"]["added"] = added
        report["dictionaries"]["removed"] = removed
        if added or removed:
            report["detected_updates"] = True
    except Exception as e:
        report["dictionaries"]["error"] = str(e)

    # ── 2) Sentinel fingerprints for a few (dict, letter) ─────
    base = f"https://abadis.ir/{args.sample_dict}/"
    for letter in args.sample_letters:
        try:
            # page 1 to learn max_pages
            html1 = fetch(f"{base}?ch={letter}")
            _, max_pages = parse_word_list_page(html1)
            pages = sentinel_pages(max_pages)
            for page in pages:
                if page == 1:
                    html = html1
                else:
                    html = fetch(f"{base}?ch={letter}&pn={page}")
                fp = compute_fingerprint(html)
                report["samples"].append({
                    "dict": args.sample_dict,
                    "letter": letter,
                    "page": page,
                    "hash": fp.word_list_hash,
                    "count": fp.word_count,
                })
        except Exception as e:
            report["samples"].append({
                "dict": args.sample_dict,
                "letter": letter,
                "error": str(e),
            })

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Wrote {args.out}")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not report["detected_updates"] else 2


if __name__ == "__main__":
    sys.exit(main())
