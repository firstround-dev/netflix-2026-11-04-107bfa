"""SQLite connection and schema."""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS question_sets (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    locales     TEXT NOT NULL,              -- JSON list of locale codes
    status      TEXT NOT NULL DEFAULT 'draft',  -- draft | locked
    created_by  TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    locked_by   TEXT,
    locked_at   TEXT
);

CREATE TABLE IF NOT EXISTS questions (
    id             TEXT PRIMARY KEY,
    set_id         TEXT NOT NULL REFERENCES question_sets(id) ON DELETE CASCADE,
    position       INTEGER NOT NULL,
    prompt         TEXT NOT NULL,
    options        TEXT NOT NULL,           -- JSON list of exactly four strings
    correct_index  INTEGER NOT NULL,
    created_by     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS translations (
    id            TEXT PRIMARY KEY,
    question_id   TEXT NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    locale        TEXT NOT NULL,
    prompt        TEXT NOT NULL,
    options       TEXT NOT NULL,            -- JSON list, same order as the English options
    status        TEXT NOT NULL,            -- draft | approved | rejected
    source        TEXT NOT NULL,            -- ai | human  (who wrote the current text)
    updated_by    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    reviewed_by   TEXT,
    reviewed_at   TEXT,
    review_note   TEXT,
    version       INTEGER NOT NULL DEFAULT 1,
    UNIQUE (question_id, locale)
);

CREATE TABLE IF NOT EXISTS events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    set_id          TEXT NOT NULL,
    question_id     TEXT,
    translation_id  TEXT,
    locale          TEXT,
    actor           TEXT NOT NULL,
    action          TEXT NOT NULL,
    source          TEXT,                   -- ai | human, when text was produced
    detail          TEXT,
    at              TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS events_set_idx ON events(set_id, id);
"""


def connect(path: Path) -> sqlite3.Connection:
    """Open a connection in autocommit mode; transactions are started explicitly by the service.

    One connection serves one request, but FastAPI may run a dependency's setup, the endpoint and
    the teardown on different worker threads, so cross-thread use must be allowed.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, autocommit=True, timeout=5, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_schema(path: Path) -> None:
    conn = connect(path)
    try:
        conn.executescript(SCHEMA)
    finally:
        conn.close()
