"""Orchestrate the crawl: top up word_queue from list pages, then fetch words."""
from __future__ import annotations

import asyncio
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
from crawler.fingerprint import (
    compute_fingerprint, load_fingerprints, save_fingerprints,
    compare, newest_captured_at,
)
from datetime import datetime, timezone, timedelta
from crawler.logger import setup_logger
from crawler.parser import WordParser, normalize_canonical
from crawler.state import DeviceState, should_process_letter
from crawler.throttle import BackoffExhausted

WORD_BASE_URL = "https://abadis.ir/fatofa/{word}/"
MAX_ATTEMPTS = 3


def _is_block_page(html: str) -> bool:
    """Detect abadis soft-block by looking at the <title> tag."""
    if not html:
        return False
    head = html[:3000].lower()
    return ("قفل شده" in head) or ("access denied" in head) or ("blocked" in head)


def _is_not_found_page(html: str) -> bool:
    """Detect abadis 404 ('page not found')."""
    if not html:
        return False
    head = html[:3000]
    return "صفحه مورد نظر پیدا نشد" in head


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
    empty_retries: Optional[int] = None,
) -> None:
    if empty_retries is None:
        conn.execute(
            "INSERT INTO crawl_pages "
            "(dictionary_slug, letter, page_number, status, words_found, last_error, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, datetime('now')) "
            "ON CONFLICT(dictionary_slug, letter, page_number) DO UPDATE SET "
            "status=excluded.status, words_found=excluded.words_found, "
            "last_error=excluded.last_error, updated_at=excluded.updated_at",
            (slug, letter, pn, status, words_found, error),
        )
    else:
        conn.execute(
            "INSERT INTO crawl_pages "
            "(dictionary_slug, letter, page_number, status, words_found, "
            " last_error, updated_at, empty_retries) "
            "VALUES (?, ?, ?, ?, ?, ?, datetime('now'), ?) "
            "ON CONFLICT(dictionary_slug, letter, page_number) DO UPDATE SET "
            "status=excluded.status, words_found=excluded.words_found, "
            "last_error=excluded.last_error, updated_at=excluded.updated_at, "
            "empty_retries=excluded.empty_retries",
            (slug, letter, pn, status, words_found, error, empty_retries),
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
    restrict_dicts: list[str] | None = None,
    restrict_letters: list[str] | None = None,
    progress: dict | None = None,
) -> None:
    dictionaries = settings.load_dictionaries()
    if restrict_dicts:
        dictionaries = [d for d in dictionaries if d["slug"] in restrict_dicts]

    letters = settings.load_letters()
    if restrict_letters:
        letters = [l for l in letters if l in restrict_letters]
    else:
        # sort by least-covered letter if progress info is available
        coverage = None
        if progress and "per_letter" in progress:
            coverage = progress["per_letter"]
        else:
            try:
                rows = conn.execute(
                    "SELECT substr(w.canonical,1,1) AS l, COUNT(*) AS c "
                    "FROM word_queue q JOIN words w ON w.id=q.word_id "
                    "WHERE q.status='done' GROUP BY l"
                ).fetchall()
                coverage = {r["l"]: r["c"] for r in rows}
            except Exception:
                coverage = {}
        if coverage:
            letters = sorted(letters, key=lambda l: coverage.get(l, 0))
            log.info(
                "Letter order by coverage: "
                + ", ".join(
                    f"{l}({coverage.get(l,0)})" for l in letters[:6]
                )
                + ("..." if len(letters) > 6 else "")
            )

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
        # Block is over: give previously failed words another chance
        with transaction(conn):
            recovered = conn.execute(
                "UPDATE word_queue SET status='pending', attempts=0, "
                "last_error=NULL "
                "WHERE status='failed' AND ("
                "  last_error LIKE '%parse None%' "
                "  OR last_error LIKE '%HTTP 5%' "
                "  OR last_error LIKE '%HTTP 429%' "
                "  OR last_error LIKE '%no html%'"
                ")"
            ).rowcount
        if recovered:
            log.info(f"Recovered {recovered} failed word(s) after block cleared")

    consecutive_empty = 0
    MAX_CONSECUTIVE_EMPTY = 5
    skipped_recently = 0

    for d in dictionaries:
        slug = d["slug"]
        base_url = d["base_url"]
        ensure_dictionary(conn, slug, base_url, d.get("display_name"))

        for letter in letters:
            if not should_process_letter(state, letter):
                continue

            # ── Fingerprint check: skip if recently verified ──
            # BUT: never skip if there are pending/failed pages for this
            # (dict, letter). Those need retry (e.g., a page that was 0
            # words during a block, or a genuinely failed fetch).
            has_unfinished = conn.execute(
                "SELECT 1 FROM crawl_pages "
                "WHERE dictionary_slug=? AND letter=? "
                "AND status IN ('pending', 'failed') LIMIT 1",
                (slug, letter),
            ).fetchone() is not None

            if not has_unfinished:
                last_seen = newest_captured_at(conn, slug, letter)
                if last_seen:
                    try:
                        ts = datetime.fromisoformat(last_seen).replace(
                            tzinfo=timezone.utc
                        )
                        age = datetime.now(timezone.utc) - ts
                        if age < timedelta(hours=24):
                            skipped_recently += 1
                            if skipped_recently <= 3:
                                log.info(
                                    f"list {slug}/{letter}: verified {age} ago, skipping"
                                )
                            continue
                    except Exception:
                        pass

            stored_fps = load_fingerprints(conn, slug, letter)
            if stored_fps:
                fetched_fps = {}
                fp_ok = True
                for fp_page in list(stored_fps.keys())[:3]:
                    fp_url = _page_url(base_url, letter, fp_page)
                    fp_res = await fetcher.fetch(fp_url)
                    if not fp_res.html:
                        fp_ok = False
                        break
                    fetched_fps[fp_page] = compute_fingerprint(fp_res.html)
                if fp_ok:
                    cmp = compare(stored_fps, fetched_fps)
                    if not cmp["changed"]:
                        log.info(
                            f"list {slug}/{letter}: unchanged, skipping"
                        )
                        save_fingerprints(conn, slug, letter, fetched_fps)
                        continue
                    log.warning(
                        f"list {slug}/{letter}: UPDATED: {cmp['changes']}"
                    )

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

            # Pagination: the widget is a sliding window (~10 pages), so
            # max_pages from page 1 is NOT the true end. Trust an empty
            # page instead (with one 3s-delay retry to rule out flakes).
            fp_pages_seen = {1: compute_fingerprint(result.html)}
            pn = 2
            MAX_SAFETY_PAGES = 300
            while pn <= MAX_SAFETY_PAGES:
                if _count_pending(conn) >= target:
                    if skipped_recently > 3:
                        log.info(f"skipped {skipped_recently - 3} more recently verified list(s)")
                    break
                if _is_page_done(conn, slug, letter, pn):
                    pn += 1
                    continue
                url = _page_url(base_url, letter, pn)
                result = await fetcher.fetch(url)
                if result.error or not result.html:
                    with transaction(conn):
                        _mark_page(conn, slug, letter, pn, "failed", 0,
                                   result.error or "no html")
                    pn += 1
                    continue
                try:
                    hrefs, _ = parse_word_list_page(result.html)
                except Exception as e:
                    with transaction(conn):
                        _mark_page(conn, slug, letter, pn, "failed", 0, str(e))
                    pn += 1
                    continue
                if len(hrefs) == 0:
                    await asyncio.sleep(3)
                    retry = await fetcher.fetch(url)
                    if retry.html:
                        hrefs, _ = parse_word_list_page(retry.html)
                    if len(hrefs) == 0:
                        # Is it a block page?
                        if _is_block_page(result.html) or _is_block_page(retry.html or ""):
                            log.warning(
                                f"list {slug}/{letter}/{pn}: 0 words, BLOCKED "
                                "(pending retry)"
                            )
                            with transaction(conn):
                                _mark_page(conn, slug, letter, pn, "pending", 0,
                                           "BLOCKED", empty_retries=0)
                            consecutive_empty += 1
                            if consecutive_empty >= MAX_CONSECUTIVE_EMPTY:
                                log.error(
                                    "Circuit breaker: consecutive blocked list "
                                    "pages. Stopping top-up."
                                )
                                return
                            break

                        # Not a block page — could still be a soft-empty
                        # (blank 200 OK) or the real end of letter. Track
                        # retries across runs so transient blocks resolve.
                        row = conn.execute(
                            "SELECT empty_retries, words_found, status "
                            "FROM crawl_pages "
                            "WHERE dictionary_slug=? AND letter=? AND page_number=?",
                            (slug, letter, pn),
                        ).fetchone()
                        prev = (row["empty_retries"] if row else 0) or 0
                        retries = prev + 1

                        if retries < 3:
                            log.info(
                                f"list {slug}/{letter}/{pn}: 0 words, "
                                f"suspect empty (retry {retries}/3)"
                            )
                            with transaction(conn):
                                _mark_page(conn, slug, letter, pn, "pending", 0,
                                           f"empty {retries}/3",
                                           empty_retries=retries)
                            # don't increment consecutive_empty here — this is
                            # a local end-of-letter signal, not a block
                            break
                        else:
                            log.info(
                                f"list {slug}/{letter}/{pn}: 0 words, "
                                f"confirmed end of letter ({retries}/3)"
                            )
                            with transaction(conn):
                                _mark_page(conn, slug, letter, pn, "done", 0,
                                           None, empty_retries=retries)
                            break
                with transaction(conn):
                    for href in hrefs:
                        _insert_word_href(conn, href)
                    _mark_page(conn, slug, letter, pn, "done", len(hrefs))
                fp_pages_seen[pn] = compute_fingerprint(result.html)
                log.info(f"list {slug}/{letter}/{pn}: {len(hrefs)} words")
                pn += 1

            # Save fingerprints for first, mid, last discovered page
            if fp_pages_seen:
                pages = sorted(fp_pages_seen.keys())
                if len(pages) >= 3:
                    keep = {pages[0], pages[len(pages)//2], pages[-1]}
                else:
                    keep = set(pages)
                try:
                    save_fingerprints(
                        conn, slug, letter,
                        {p: fp_pages_seen[p] for p in keep},
                    )
                except Exception as e:
                    log.debug(f"fingerprint save failed: {e}")


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

    # Try /fatofa/ first, then per-dictionary URLs (some words like
    # ائتجار have no aggregator page, only appear in specific dicts).
    urls_to_try = [WORD_BASE_URL.format(word=quote(display))]
    for dict_slug in ("dehkhoda", "moeen", "amid", "parsi", "farhang"):
        urls_to_try.append(
            f"https://abadis.ir/{dict_slug}/{quote(display)}/"
        )
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
            if _is_block_page(result.html):
                last_error = f"BLOCKED at {url}"
                log.warning(
                    f"block detected for {canonical}, skipping remaining URLs"
                )
                try:
                    from pathlib import Path as _P
                    dbg = _P("/tmp") / f"blocked_{canonical.replace('/', '_')}.html"
                    dbg.write_text(result.html, encoding="utf-8")
                except Exception:
                    pass
                break
            if _is_not_found_page(result.html):
                # This URL genuinely 404'd — try next URL
                last_error = f"NOT_FOUND at {url}"
                continue
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

    if last_error.startswith("BLOCKED"):
        with transaction(conn):
            conn.execute(
                "UPDATE word_queue SET status='pending' WHERE word_id=?",
                (word_id,),
            )
        log.warning(f"word blocked: {canonical}")
        return "blocked"

    if last_error.startswith("NOT_FOUND"):
        # May be genuine 404 or soft-block masquerading as 404.
        # Bump attempts; give up after 3 (real 404s settle fast).
        with transaction(conn):
            row = conn.execute(
                "SELECT attempts FROM word_queue WHERE word_id=?", (word_id,)
            ).fetchone()
            attempts = (row["attempts"] if row else 0) + 1
            if attempts >= 3:
                conn.execute(
                    "UPDATE word_queue SET status='not_found', "
                    "attempts=?, last_error=?, updated_at=datetime('now') "
                    "WHERE word_id=?",
                    (attempts, last_error, word_id),
                )
                log.warning(f"word 404 (final, attempts={attempts}): {canonical}")
            else:
                conn.execute(
                    "UPDATE word_queue SET status='pending', "
                    "attempts=?, last_error=?, updated_at=datetime('now') "
                    "WHERE word_id=?",
                    (attempts, last_error, word_id),
                )
                log.warning(f"word 404 (attempt {attempts}/3): {canonical}")
        return "not_found"

    with transaction(conn):
        retry = _queue_retry(conn, word_id, last_error)
    log.warning(f"word fail: {canonical}: {last_error}")
    return "retry" if retry else "failed"


async def run_crawl(
    settings, fetcher, parser: WordParser, conn: sqlite3.Connection,
    state: DeviceState, max_words: int,
    restrict_dicts: list[str] | None = None,
    restrict_letters: list[str] | None = None,
    progress: dict | None = None,
    force_top_up: bool = False,
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
    if pending < max_words or force_top_up:
        log.info(f"Queue low; topping up to {target_queue}...")
        await _top_up_queue(
            settings, fetcher, conn, state, target_queue, log,
            restrict_dicts=restrict_dicts,
            restrict_letters=restrict_letters,
            progress=progress,
        )
        log.info(f"After top-up: {_count_pending(conn)} pending")

    fetched = 0
    failed = 0
    blocked_streak = 0
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
            blocked_streak = 0
        elif outcome == "failed":
            failed += 1
            blocked_streak = 0
        elif outcome == "blocked":
            blocked_streak += 1
            if blocked_streak >= 3:
                log.error(
                    f"{blocked_streak} words blocked in a row — stopping. "
                    "Server is soft-blocking; next run will resume."
                )
                break
            # short pause before trying the next word
            await asyncio.sleep(30)

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
