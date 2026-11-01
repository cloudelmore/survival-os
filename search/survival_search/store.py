"""The SQLite catalog and FTS5 index. WAL mode: readers never block the indexer, or the reverse."""

import sqlite3
from pathlib import Path

JOURNAL_LIMIT = 64 * 1024 * 1024

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY,
    path TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    format TEXT NOT NULL,
    category TEXT NOT NULL,
    size INTEGER NOT NULL,
    mtime_ns INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'pending',
    pages_total INTEGER NOT NULL DEFAULT 0,
    pages_done INTEGER NOT NULL DEFAULT 0,
    pages_no_text INTEGER NOT NULL DEFAULT 0,
    attempts INTEGER NOT NULL DEFAULT 0,
    error TEXT
);
CREATE INDEX IF NOT EXISTS documents_state ON documents(state);
CREATE INDEX IF NOT EXISTS documents_sha256 ON documents(sha256);

CREATE TABLE IF NOT EXISTS passages (
    id INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page INTEGER NOT NULL,
    label TEXT NOT NULL,
    text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS passages_location ON passages(document_id, page);

CREATE VIRTUAL TABLE IF NOT EXISTS passages_fts USING fts5(
    text, content='passages', content_rowid='id',
    tokenize='porter unicode61 remove_diacritics 2'
);
CREATE TRIGGER IF NOT EXISTS passages_ai AFTER INSERT ON passages BEGIN
    INSERT INTO passages_fts(rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER IF NOT EXISTS passages_ad AFTER DELETE ON passages BEGIN
    INSERT INTO passages_fts(passages_fts, rowid, text) VALUES ('delete', old.id, old.text);
END;
"""


def connect(path: Path) -> sqlite3.Connection:
    """Open for writing, creating the index if needed. Only the indexer does this."""
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    # NORMAL in WAL mode may lose the last commits on power loss but cannot corrupt the database,
    # and progress is saved in the same transaction as the passages it describes.
    db.execute("PRAGMA synchronous=NORMAL")
    db.execute("PRAGMA foreign_keys=ON")
    # A large delete can leave a write-ahead log as big as the document's index.
    db.execute(f"PRAGMA journal_size_limit={JOURNAL_LIMIT}")
    db.executescript(SCHEMA)
    return db


def connect_readonly(path: Path) -> sqlite3.Connection | None:
    if not path.exists():
        return None
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
    db.row_factory = sqlite3.Row
    return db
