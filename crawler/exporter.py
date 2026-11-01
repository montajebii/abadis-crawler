"""Export local crawl data to CSV for GitHub PR."""
from __future__ import annotations

import csv
import sqlite3
import time
from pathlib import Path

from crawler.db import transaction
from crawler.logger import setup_logger

CSV_COLUMNS = [
    "word_canonical",
    "word_display",
    "word_pronunciation",
    "word_english_mean",
    "source_key",
    "source_title",
    "definition_text",
]


def _get_last_export(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT metric_value FROM crawl_metrics WHERE metric_key='last_export_epoch'"
    ).fetchone()
    return row["metric_value"] if row else 0


def _set_last_export(conn: sqlite3.Connection, epoch: int) -> None:
    conn.execute(
        "INSERT INTO crawl_metrics (metric_key, metric_value) "
        "VALUES ('last_export_epoch', ?) "
        "ON CONFLICT(metric_key) DO UPDATE SET "
        "metric_value=excluded.metric_value, measured_at=datetime('now')",
        (epoch,),
    )


def export_csv(conn: sqlite3.Connection, output_path: Path) -> int:
    log = setup_logger("exporter")
    last_epoch = _get_last_export(conn)

    # Snapshot the current time BEFORE the query, so any word marked done
    # during export will be caught on the next run.
    query_epoch = int(time.time())

    rows = conn.execute(
        "SELECT w.canonical, w.display_form, w.pronunciation, w.english_mean, "
        "       d.source_key, d.source_title, d.content_text "
        "FROM word_queue q "
        "JOIN words w ON w.id = q.word_id "
        "JOIN definitions d ON d.word_id = w.id "
        "WHERE q.status = 'done' "
        "  AND CAST(strftime('%s', q.updated_at) AS INTEGER) > ? "
        "ORDER BY w.id, d.source_key",
        (last_epoch,),
    ).fetchall()

    if not rows:
        log.info("No new data to export")
        return 0

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(CSV_COLUMNS)
        for r in rows:
            writer.writerow([
                r["canonical"],
                r["display_form"],
                r["pronunciation"] or "",
                r["english_mean"] or "",
                r["source_key"],
                r["source_title"] or "",
                r["content_text"],
            ])

    with transaction(conn):
        _set_last_export(conn, query_epoch)

    log.info(f"Exported {len(rows)} rows to {output_path}")
    return len(rows)
