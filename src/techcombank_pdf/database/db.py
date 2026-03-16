"""SQLite database connection and schema management."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from techcombank_pdf.config import DATABASE_PATH

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS statements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_file TEXT NOT NULL,
    statement_date TEXT,
    due_date TEXT,
    card_number_masked TEXT,
    card_holder_name TEXT,
    total_due TEXT,
    min_payment TEXT,
    credit_limit TEXT,
    period_start TEXT,
    period_end TEXT,
    page_count INTEGER,
    parse_method TEXT,
    imported_at TEXT DEFAULT (datetime('now')),
    UNIQUE(source_file, statement_date)
);

CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    statement_id INTEGER NOT NULL,
    transaction_date TEXT NOT NULL,
    posting_date TEXT,
    description TEXT NOT NULL,
    original_amount TEXT NOT NULL,
    original_currency TEXT DEFAULT 'VND',
    billing_amount_vnd TEXT NOT NULL,
    transaction_type TEXT NOT NULL CHECK(transaction_type IN ('debit', 'credit')),
    category TEXT,
    merchant_name TEXT,
    card_last_four TEXT,
    reference_number TEXT,
    FOREIGN KEY (statement_id) REFERENCES statements(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_txn_date ON transactions(transaction_date);
CREATE INDEX IF NOT EXISTS idx_txn_type ON transactions(transaction_type);
CREATE INDEX IF NOT EXISTS idx_txn_statement ON transactions(statement_id);
"""


def get_connection(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Get a SQLite connection with WAL mode and foreign keys enabled."""
    db_path = Path(db_path) if db_path else DATABASE_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Initialize database with schema and return connection."""
    conn = get_connection(db_path)
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    return conn
