-- db/schema.sql
-- منبع حقیقت برای هر دو دیتابیس:
--   • دیتابیس محلی crawler (روی Termux)
--   • دیتابیس مرکزی ساخته‌شده توسط GitHub Actions
-- همه‌ی جداول IF NOT EXISTS دارند تا بتوان این فایل را روی
-- هر دو دیتابیس بدون مشکل اجرا کرد.

PRAGMA foreign_keys = ON;

-- ── دیکشنری‌ها ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS dictionaries (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    slug          TEXT NOT NULL UNIQUE,
    base_url      TEXT NOT NULL,
    display_name  TEXT,
    is_active     INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ── واژه‌ها (سراسری، بدون تکرار) ────────────────────────────
CREATE TABLE IF NOT EXISTS words (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical       TEXT NOT NULL UNIQUE,
    display_form    TEXT NOT NULL,
    pronunciation   TEXT,
    english_mean    TEXT,
    first_seen_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ── بخش‌های معنایی (دهخدا، معین، عمید، ...) ─────────────────
CREATE TABLE IF NOT EXISTS definitions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    word_id       INTEGER NOT NULL,
    source_key    TEXT NOT NULL,
    source_title  TEXT,
    content_text  TEXT,
    fetched_at    TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (word_id) REFERENCES words(id) ON DELETE CASCADE,
    UNIQUE(word_id, source_key)
);

CREATE INDEX IF NOT EXISTS idx_definitions_word   ON definitions(word_id);
CREATE INDEX IF NOT EXISTS idx_definitions_source ON definitions(source_key);

-- ── وضعیت صفحات فهرست (فقط در دیتابیس محلی) ────────────────
CREATE TABLE IF NOT EXISTS crawl_pages (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    dictionary_slug  TEXT NOT NULL,
    letter           TEXT NOT NULL,
    page_number      INTEGER NOT NULL DEFAULT 1,
    status           TEXT NOT NULL DEFAULT 'pending', -- pending | done | failed
    words_found      INTEGER DEFAULT 0,
    last_error       TEXT,
    updated_at       TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(dictionary_slug, letter, page_number)
);

-- ── صف واژه‌ها (فقط در دیتابیس محلی) ───────────────────────
CREATE TABLE IF NOT EXISTS word_queue (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    word_id       INTEGER NOT NULL,
    status        TEXT NOT NULL DEFAULT 'pending',   -- pending | done | failed
    attempts      INTEGER NOT NULL DEFAULT 0,
    last_error    TEXT,
    updated_at    TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (word_id) REFERENCES words(id) ON DELETE CASCADE,
    UNIQUE(word_id)
);

CREATE INDEX IF NOT EXISTS idx_word_queue_status ON word_queue(status);

-- ── متریک‌ها ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS crawl_metrics (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    metric_key    TEXT NOT NULL UNIQUE,
    metric_value  INTEGER NOT NULL,
    measured_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ── اثر انگشت صفحات فهرست (کشف به‌روزرسانی) ────────────
CREATE TABLE IF NOT EXISTS crawl_fingerprints (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    dictionary_slug TEXT NOT NULL,
    letter          TEXT NOT NULL,
    sample_page     INTEGER NOT NULL,
    word_list_hash  TEXT NOT NULL,
    word_count      INTEGER NOT NULL,
    first_word      TEXT,
    last_word       TEXT,
    captured_at     TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(dictionary_slug, letter, sample_page)
);

-- ── برای migration: در db.py مقداردهی می‌شود ────────────
-- empty_retries INTEGER NOT NULL DEFAULT 0
