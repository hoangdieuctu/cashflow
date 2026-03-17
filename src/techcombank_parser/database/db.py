"""SQLite database connection and schema management."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from techcombank_parser.config import DATABASE_PATH

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS statements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_file TEXT NOT NULL,
    statement_type TEXT NOT NULL DEFAULT 'credit_card' CHECK(statement_type IN ('credit_card', 'bank_account')),
    statement_date TEXT,
    due_date TEXT,
    card_number_masked TEXT,
    card_holder_name TEXT,
    total_due TEXT,
    min_payment TEXT,
    credit_limit TEXT,
    period_start TEXT,
    period_end TEXT,
    account_number TEXT,
    opening_balance TEXT,
    ending_balance TEXT,
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
    running_balance TEXT,
    FOREIGN KEY (statement_id) REFERENCES statements(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_txn_date ON transactions(transaction_date);
CREATE INDEX IF NOT EXISTS idx_txn_type ON transactions(transaction_type);
CREATE INDEX IF NOT EXISTS idx_txn_statement ON transactions(statement_id);

CREATE TABLE IF NOT EXISTS category_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_type TEXT NOT NULL CHECK(match_type IN ('contains', 'endswith')),
    pattern TEXT NOT NULL,
    category TEXT NOT NULL,
    priority INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(match_type, pattern)
);
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
    _migrate(conn)
    conn.commit()
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """Apply incremental migrations for columns added after initial schema."""
    existing_stmt_cols = {
        row[1] for row in conn.execute("PRAGMA table_info(statements)").fetchall()
    }
    existing_txn_cols = {
        row[1] for row in conn.execute("PRAGMA table_info(transactions)").fetchall()
    }

    migrations = []

    if "statement_type" not in existing_stmt_cols:
        migrations.append(
            "ALTER TABLE statements ADD COLUMN statement_type TEXT NOT NULL DEFAULT 'credit_card'"
        )
    if "account_number" not in existing_stmt_cols:
        migrations.append("ALTER TABLE statements ADD COLUMN account_number TEXT")
    if "opening_balance" not in existing_stmt_cols:
        migrations.append("ALTER TABLE statements ADD COLUMN opening_balance TEXT")
    if "ending_balance" not in existing_stmt_cols:
        migrations.append("ALTER TABLE statements ADD COLUMN ending_balance TEXT")
    if "running_balance" not in existing_txn_cols:
        migrations.append("ALTER TABLE transactions ADD COLUMN running_balance TEXT")

    for sql in migrations:
        conn.execute(sql)
