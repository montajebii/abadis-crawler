"""Fingerprint list pages to detect upstream updates (pacman-style)."""
from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from typing import Optional

from crawler.db import transaction
from crawler.discovery import extract_word_slug, parse_word_list_page
from crawler.parser import normalize_canonical


@dataclass
class Fingerprint:
    word_list_hash: str
    word_count: int
    first_word: Optional[str]
    last_word: Optional[str]


def compute_fingerprint(html: str) -> Fingerprint:
    """SHA256 over the sorted canonical word list on the page."""
    hrefs, _ = parse_word_list_page(html)
    words: list[str] = []
    for href in hrefs:
        slug = extract_word_slug(href)
        if slug:
            words.append(normalize_canonical(slug))
    if not words:
        return Fingerprint("", 0, None, None)
    payload = "\n".join(sorted(words)).encode("utf-8")
    return Fingerprint(
        word_list_hash=hashlib.sha256(payload).hexdigest(),
        word_count=len(words),
        first_word=words[0],
        last_word=words[-1],
    )


def sentinel_pages(max_pages: int) -> list[int]:
    """Pick first, middle, last pages."""
    if max_pages <= 3:
        return list(range(1, max_pages + 1))
    return [1, max_pages // 2, max_pages]


def load_fingerprints(
    conn: sqlite3.Connection, slug: str, letter: str,
) -> dict[int, Fingerprint]:
    rows = conn.execute(
        "SELECT sample_page, word_list_hash, word_count, first_word, last_word "
        "FROM crawl_fingerprints WHERE dictionary_slug=? AND letter=?",
        (slug, letter),
    ).fetchall()
    return {
        r["sample_page"]: Fingerprint(
            word_list_hash=r["word_list_hash"],
            word_count=r["word_count"],
            first_word=r["first_word"],
            last_word=r["last_word"],
        )
        for r in rows
    }


def save_fingerprints(
    conn: sqlite3.Connection, slug: str, letter: str,
    fps: dict[int, Fingerprint],
) -> None:
    with transaction(conn):
        for page, fp in fps.items():
            conn.execute(
                "INSERT INTO crawl_fingerprints "
                "(dictionary_slug, letter, sample_page, word_list_hash, "
                " word_count, first_word, last_word, captured_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now')) "
                "ON CONFLICT(dictionary_slug, letter, sample_page) DO UPDATE SET "
                "word_list_hash=excluded.word_list_hash, "
                "word_count=excluded.word_count, "
                "first_word=excluded.first_word, "
                "last_word=excluded.last_word, "
                "captured_at=excluded.captured_at",
                (slug, letter, page, fp.word_list_hash, fp.word_count,
                 fp.first_word, fp.last_word),
            )


def newest_captured_at(
    conn: sqlite3.Connection, slug: str, letter: str,
) -> Optional[str]:
    row = conn.execute(
        "SELECT MAX(captured_at) AS ts FROM crawl_fingerprints "
        "WHERE dictionary_slug=? AND letter=?",
        (slug, letter),
    ).fetchone()
    return row["ts"] if row else None


def compare(
    stored: dict[int, Fingerprint],
    fetched: dict[int, Fingerprint],
) -> dict:
    changes = []
    for page in stored.keys() & fetched.keys():
        old, new = stored[page], fetched[page]
        if old.word_list_hash != new.word_list_hash:
            changes.append({
                "page": page,
                "old_count": old.word_count,
                "new_count": new.word_count,
                "delta": new.word_count - old.word_count,
                "old_first": old.first_word,
                "new_first": new.first_word,
                "old_last": old.last_word,
                "new_last": new.last_word,
            })
    return {
        "changed": bool(changes),
        "changes": changes,
        "new_pages": sorted(fetched.keys() - stored.keys()),
        "removed_pages": sorted(stored.keys() - fetched.keys()),
    }
