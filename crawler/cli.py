"""Command-line interface for the crawler."""
from __future__ import annotations

import argparse
import json
import asyncio
import sys

from crawler.config import Settings
from crawler.db import connect, init_schema
from crawler.exporter import export_csv
from crawler.fetcher import Fetcher
from crawler.logger import setup_logger
from crawler.parser import WordParser
from crawler.scheduler import run_crawl
from crawler.state import load_or_create_state, save_state
from crawler.throttle import AIMDConfig, AIMDController, BackoffExhausted
from crawler.useragent import UserAgentRotator

STATE_FILE_NAME = "device_state.json"


async def _run(settings: Settings, args: argparse.Namespace) -> int:
    log = setup_logger("cli", log_dir=settings.project_root / "logs",
                       debug=settings.debug)
    log.info(f"Project root: {settings.project_root}")
    log.info(f"Local DB: {settings.local_db_path}")
    log.info(f"Output CSV: {settings.output_csv}")

    conn = connect(settings.local_db_path)
    init_schema(conn, settings.schema_path)

    if args.rescan:
        slug, letter = args.rescan
        with transaction(conn):
            conn.execute(
                "DELETE FROM crawl_pages WHERE dictionary_slug=? AND letter=?",
                (slug, letter),
            )
            conn.execute(
                "DELETE FROM crawl_fingerprints WHERE dictionary_slug=? AND letter=?",
                (slug, letter),
            )
        log.info(f"Cleared crawl_pages and crawl_fingerprints for {slug}/{letter}")

    state_path = settings.project_root / STATE_FILE_NAME
    state = load_or_create_state(
        state_path,
        device_id=args.device_id or settings.device_id,
        shard_count=args.shard_count or settings.shard_count,
    )
    if args.shard_index is not None:
        state.shard_index = args.shard_index
    log.info(
        f"Device: {state.device_id[:8]}... "
        f"shard={state.shard_index}/{state.shard_count}"
    )

    rate_cfg = settings.load_rate_config()
    aimd_cfg = AIMDConfig.from_dict(rate_cfg)
    throttle = AIMDController(
        aimd_cfg, initial_min=state.aimd_min, initial_max=state.aimd_max
    )
    throttle.consecutive_429 = state.consecutive_429
    throttle.success_streak = state.success_streak

    ua_cfg = rate_cfg.get("useragent", {})
    ua = UserAgentRotator(
        rotate_min=int(ua_cfg.get("rotate_every_n_requests_min", 20)),
        rotate_max=int(ua_cfg.get("rotate_every_n_requests_max", 50)),
    )

    blocked = rate_cfg.get("blocked_domains", [])
    block_types = rate_cfg.get(
        "block_resources", ["image", "media", "font", "stylesheet"]
    )

    parser = WordParser(settings.source_mapping_path)
    max_words = args.max_words or settings.max_words_per_run
    log.info(f"Budget: max_words={max_words}")

    # Optional progress fetched from a URL (e.g., latest release on GitHub)
    progress = None
    if args.progress_url:
        try:
            import urllib.request
            with urllib.request.urlopen(args.progress_url, timeout=15) as r:
                progress = json.loads(r.read().decode("utf-8"))
            log.info(f"Fetched progress from {args.progress_url}")
        except Exception as e:
            log.warning(f"Could not fetch progress from URL: {e}")

    if args.dict:
        log.info(f"Restricting to dictionaries: {args.dict}")
    if args.letters:
        log.info(f"Restricting to letters: {args.letters}")

    exit_code = 0
    try:
        async with Fetcher(
            throttle, ua, blocked, block_types, headless=args.headless
        ) as fetcher:
            await run_crawl(
                settings, fetcher, parser, conn, state, max_words,
                restrict_dicts=args.dict,
                restrict_letters=args.letters,
                progress=progress,
                force_top_up=args.force_top_up,
            )
    except BackoffExhausted as e:
        log.error(f"Rate limit exhausted, will resume next run: {e}")
        exit_code = 2
    except KeyboardInterrupt:
        log.info("Interrupted by user")
        exit_code = 130
    finally:
        save_state(state, state_path)
        conn.close()

    # Export after crawl
    try:
        conn2 = connect(settings.local_db_path)
        init_schema(conn2, settings.schema_path)
        export_csv(conn2, settings.output_csv)
        conn2.close()
    except Exception:
        setup_logger("cli").exception("Export failed")
        exit_code = exit_code or 3

    return exit_code


def main() -> int:
    ap = argparse.ArgumentParser(description="Abadis distributed crawler")
    ap.add_argument("--max-words", type=int, default=None,
                    help="Max word pages to fetch this run")
    ap.add_argument("--device-id", type=str, default=None,
                    help="Unique device ID (or set DEVICE_ID in .env)")
    ap.add_argument("--shard-count", type=int, default=None,
                    help="Total number of shards for letter distribution")
    ap.add_argument("--no-headless", dest="headless", action="store_false",
                    default=True, help="Show browser window (debug)")
    ap.add_argument("--dict", action="append", default=None,
                    help="Restrict to specific dictionary slugs (repeatable)")
    ap.add_argument("--letters", nargs="+", default=None,
                    help="Restrict to specific letters (e.g. --letters د ر)")
    ap.add_argument("--progress-url", type=str, default=None,
                    help="URL to a progress.json file (used for least-covered ordering)")
    ap.add_argument("--shard-index", type=int, default=None,
                    help="Override the computed shard index (0-based)")
    ap.add_argument("--rescan", nargs=2, metavar=("DICT", "LETTER"),
                    default=None,
                    help="Force re-scan of a dict:letter (clears crawl_pages and crawl_fingerprints)")
    ap.add_argument("--force-top-up", action="store_true", default=False,
                    help="Trigger top-up even if pending >= max_words")
    args = ap.parse_args()

    settings = Settings.load()
    try:
        return asyncio.run(_run(settings, args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
