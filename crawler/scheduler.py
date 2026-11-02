"""Orchestrate the crawl: top up word_queue from list pages, then fetch words."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from crawler.db import (
    ensure_dictionary,
    get_or_create_word,
    insert_definition,
    mark_word,
    transaction,
    word_is_done,
)
from crawler.discovery import extract_word_slug, parse_word_list_page
from crawler.logger import setup_logger
from crawler.parser import WordParser, normalize_canonical
from crawler.state import DeviceState, should_process_letter
from crawler.throttle import BackoffExhausted

WORD_BASE_URL = "https://abadis.ir/fatofa/{word}/"
MAX_ATTEMPTS = 3


def _page_url(base_url: str, letter: str, page_number: int) -> str:
    base = base_url.rstrip("/")
    if page_number == 1:
        return f"{base}/?ch={quote(letter)}"
    return f"{base}/?ch={quote(letter)}&pn={page_number}"


def _is_page_done(conn: sqlite3.Connection, slug: str, letter: str, pn: int) -> bool:
    row = conn.execute(
        "SELECT status FROM crawl_pages "
        "WHERE dictionary_slug=? AND letter=? AND page_number=?",
        (slug, letter, pn),
    ).fetchone()
    return row is not None and row["status"] == "done"


def _mark_page(
    conn: sqlite3.Connection,
    slug: str,
    letter: str,
    pn: int,
    status: str,
    words_found: int = 0,
    error: Optional[str] = None,
) -> None:
    conn.execute(
        "INSERT INTO crawl_pages "
        "(dictionary_slug, letter, page_number, status, words_found, last_error, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, datetime('now')) "
        "ON CONFLICT(dictionary_slug, letter, page_number) DO UPDATE SET "
        "status=excluded.status, words_found=excluded.words_found, "
        "last_error=excluded.last_error, updated_at=excluded.updated_at",
        (slug, letter, pn, status, words_found, error),
    )


def _insert_word_href(conn: sqlite3.Connection, href: str) -> Optional[int]:
    slug = extract_word_slug(href)
    if not slug:
        return None
    canonical = normalize_canonical(slug)
    if not canonical:
        return None
    word_id = get_or_create_word(conn, canonical, slug)
    conn.execute(
        "INSERT OR IGNORE INTO word_queue (word_id, status) VALUES (?, 'pending')",
        (word_id,),
    )
    return word_id


def _count_pending(conn: sqlite3.Connection) -> int:
    return conn.execute(
        "SELECT COUNT(*) AS c FROM word_queue WHERE status='pending'"
    ).fetchone()["c"]


def _pop_pending(
    conn: sqlite3.Connection, exclude: Optional[set[int]] = None
) -> Optional[sqlite3.Row]:
    exclude = exclude or set()
    rows = conn.execute(
        "SELECT q.id AS queue_id, q.word_id, q.attempts, "
        "       w.canonical, w.display_form "
        "FROM word_queue q JOIN words w ON w.id = q.word_id "
        "WHERE q.status='pending' ORDER BY q.id"
    ).fetchall()
    for row in rows:
        if row["word_id"] not in exclude:
            return row
    return None


def _queue_retry(conn: sqlite3.Connection, word_id: int, error: str) -> bool:
    """Mark failed; if attempts < MAX_ATTEMPTS, reset to pending for retry."""
    mark_word(conn, word_id, "failed", error)
    row = conn.execute(
        "SELECT attempts FROM word_queue WHERE word_id=?", (word_id,)
    ).fetchone()
    if row and row["attempts"] < MAX_ATTEMPTS:
        conn.execute(
            "UPDATE word_queue SET status='pending' WHERE word_id=?", (word_id,)
        )
        return True
    return False


def _reset_fetching(conn: sqlite3.Connection) -> int:
    """Reset 'fetching' rows left behind by a crashed previous run."""
    with transaction(conn):
        cur = conn.execute(
            "UPDATE word_queue SET status='pending' WHERE status='fetching'"
        )
    return cur.rowcount


async def _top_up_queue(
    settings, fetcher, conn: sqlite3.Connection, state: DeviceState,
    target: int, log,
) -> None:
    dictionaries = settings.load_dictionaries()
    letters = settings.load_letters()

    # ── Probe: a known-good page must return >0 words. ─────────
    # abadis sometimes serves a stripped 200 page without div.boxLi
    # when it soft-blocks the client. Detect this early.
    probe_url = _page_url("https://abadis.ir/dehkhoda/", letters[0], 1)
    probe = await fetcher.fetch(probe_url)
    if probe.error or not probe.html:
        log.warning(f"probe fetch failed: {probe.error}")
    else:
        try:
            probe_hrefs, _ = parse_word_list_page(probe.html)
        except Exception:
            probe_hrefs = []
        if len(probe_hrefs) == 0:
            try:
                Path("/tmp").joinpath("probe_blocked.html").write_text(
                    probe.html, encoding="utf-8"
                )
            except Exception:
                pass
            log.error(
                "SERVER APPEARS TO BE BLOCKING: probe page returned 0 words. "
                "Saved to /tmp/probe_blocked.html. Stopping top-up for now."
            )
            return
        log.info(f"Probe OK: {len(probe_hrefs)} words on {probe_url}")

    consecutive_empty = 0
    MAX_CONSECUTIVE_EMPTY = 5

    for d in dictionaries:
        slug = d["slug"]
        base_url = d["base_url"]
        ensure_dictionary(conn, slug, base_url, d.get("display_name"))

        for letter in letters:
            if not should_process_letter(state, letter):
                continue

            url = _page_url(base_url, letter, 1)
            result = await fetcher.fetch(url)  # no wait_selector
            if result.error or not result.html:
                with transaction(conn):
                    _mark_page(conn, slug, letter, 1, "failed", 0,
                               result.error or "no html")
                log.warning(f"list fetch fail: {url}: {result.error}")
                continue

            try:
                hrefs, max_pages = parse_word_list_page(result.html)
            except Exception as e:
                with transaction(conn):
                    _mark_page(conn, slug, letter, 1, "failed", 0, str(e))
                log.exception(f"parse fail: {url}")
                continue

            if len(hrefs) == 0:
                consecutive_empty += 1
                log.warning(
                    f"list {slug}/{letter}/1: 0 words "
                    f"(consecutive_empty={consecutive_empty})"
                )
                if consecutive_empty >= MAX_CONSECUTIVE_EMPTY:
                    try:
                        Path("/tmp").joinpath("list_blocked.html").write_text(
                            result.html, encoding="utf-8"
                        )
                    except Exception:
                        pass
                    log.error(
                        f"Circuit breaker: {consecutive_empty} consecutive "
                        "empty list pages. Server likely soft-blocking. "
                        "Stopping top-up. HTML saved to /tmp/list_blocked.html."
                    )
                    return
                continue
            consecutive_empty = 0

            with transaction(conn):
                for href in hrefs:
                    _insert_word_href(conn, href)
                _mark_page(conn, slug, letter, 1, "done", len(hrefs))

            log.info(
                f"list {slug}/{letter}/1: {len(hrefs)} words, max_pages={max_pages}"
            )
            if _count_pending(conn) >= target:
                return

            for pn in range(2, max_pages + 1):
                if _is_page_done(conn, slug, letter, pn):
                    continue
                url = _page_url(base_url, letter, pn)
                result = await fetcher.fetch(url)  # no wait_selector
                if result.error or not result.html:
                    with transaction(conn):
                        _mark_page(conn, slug, letter, pn, "failed", 0,
                                   result.error or "no html")
                    continue
                try:
                    hrefs, _ = parse_word_list_page(result.html)
                except Exception as e:
                    with transaction(conn):
                        _mark_page(conn, slug, letter, pn, "failed", 0, str(e))
                    continue
                if len(hrefs) == 0:
                    consecutive_empty += 1
                    log.warning(
                        f"list {slug}/{letter}/{pn}: 0 words "
                        f"(consecutive_empty={consecutive_empty})"
                    )
                    if consecutive_empty >= MAX_CONSECUTIVE_EMPTY:
                        log.error(
                            f"Circuit breaker: {consecutive_empty} consecutive "
                            "empty list pages. Stopping top-up."
                        )
                        return
                    continue
                consecutive_empty = 0
                with transaction(conn):
                    for href in hrefs:
                        _insert_word_href(conn, href)
                    _mark_page(conn, slug, letter, pn, "done", len(hrefs))
                log.info(f"list {slug}/{letter}/{pn}: {len(hrefs)} words")
                if _count_pending(conn) >= target:
                    return


async def _fetch_and_store(
    fetcher, parser: WordParser, conn: sqlite3.Connection,
    word_row: sqlite3.Row, log,
) -> str:
    """Return 'ok' | 'retry' | 'failed'."""
    word_id = word_row["word_id"]
    canonical = word_row["canonical"]
    display = word_row["display_form"]

    if word_is_done(conn, word_id):
        return "ok"

    with transaction(conn):
        conn.execute(
            "UPDATE word_queue SET status='fetching' WHERE word_id=?",
            (word_id,),
        )

    # Try display_form first (preserves Arabic ك/ي as in the href).
    urls_to_try = [WORD_BASE_URL.format(word=quote(display))]
    if display != canonical:
        urls_to_try.append(WORD_BASE_URL.format(word=quote(canonical)))

    last_error: str = "unknown"
    for url in urls_to_try:
        try:
            result = await fetcher.fetch(url, wait_selector="div.boxMain")
        except BackoffExhausted:
            raise

        if result.error or not result.html:
            last_error = result.error or "no html"
            continue

        try:
            parsed = parser.parse(result.html)
        except Exception as e:
            last_error = f"parse exception: {e}"
            log.exception(f"parse fail: {canonical} url={url}")
            continue

        if parsed is None:
            last_error = f"parse None at {url}"
            try:
                from pathlib import Path as _P
                dbg = _P("/tmp") / f"failed_{canonical.replace('/', '_')}.html"
                dbg.write_text(result.html, encoding="utf-8")
                log.info(f"parse None, saved HTML to {dbg}")
            except Exception:
                pass
            continue

        with transaction(conn):
            if parsed.pronunciation or parsed.english_mean:
                conn.execute(
                    "UPDATE words SET "
                    "pronunciation=COALESCE(?, pronunciation), "
                    "english_mean=COALESCE(?, english_mean) "
                    "WHERE id=?",
                    (parsed.pronunciation, parsed.english_mean, word_id),
                )
            for sec in parsed.sections:
                insert_definition(
                    conn, word_id, sec.source_key,
                    sec.source_title, sec.content_text,
                )
            mark_word(conn, word_id, "done", None)
        return "ok"

    with transaction(conn):
        retry = _queue_retry(conn, word_id, last_error)
    log.warning(f"word fail: {canonical}: {last_error}")
    return "retry" if retry else "failed"


async def run_crawl(
    settings, fetcher, parser: WordParser, conn: sqlite3.Connection,
    state: DeviceState, max_words: int,
) -> int:
    log = setup_logger("scheduler")
    reset = _reset_fetching(conn)
    if reset:
        log.info(f"Reset {reset} stuck 'fetching' rows from previous run")

    pending = _count_pending(conn)
    log.info(
        f"Start: device={state.device_id[:8]} "
        f"shard={state.shard_index}/{state.shard_count} "
        f"pending={pending} budget={max_words}"
    )

    target_queue = max(50, max_words * 3)
    if pending < max_words:
        log.info(f"Queue low; topping up to {target_queue}...")
        await _top_up_queue(settings, fetcher, conn, state, target_queue, log)
        log.info(f"After top-up: {_count_pending(conn)} pending")

    fetched = 0
    failed = 0
    tried: set[int] = set()

    while (fetched + failed) < max_words:
        word_row = _pop_pending(conn, exclude=tried)
        if word_row is None:
            log.info("No more pending words")
            break
        tried.add(word_row["word_id"])

        try:
            outcome = await _fetch_and_store(fetcher, parser, conn, word_row, log)
        except BackoffExhausted as e:
            log.error(f"Rate limit exhausted, stopping: {e}")
            with transaction(conn):
                conn.execute(
                    "UPDATE word_queue SET status='pending' WHERE word_id=?",
                    (word_row["word_id"],),
                )
            break

        if outcome == "ok":
            fetched += 1
            state.total_words_done += 1
        elif outcome == "failed":
            failed += 1

        state.total_requests = fetcher.throttle.total_requests
        state.aimd_min = fetcher.throttle.min_delay
        state.aimd_max = fetcher.throttle.max_delay
        state.success_streak = fetcher.throttle.success_streak
        state.consecutive_429 = fetcher.throttle.consecutive_429

        if (fetched + failed) % 5 == 0:
            log.info(
                f"progress: {fetched} ok / {failed} failed | "
                f"delay={state.aimd_min:.2f}-{state.aimd_max:.2f}s | "
                f"queue={_count_pending(conn)}"
            )

    log.info(f"Run done: {fetched} ok / {failed} failed")
    return fetched
