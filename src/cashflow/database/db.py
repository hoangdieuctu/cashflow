"""SQLite database connection and schema management."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from cashflow.config import DATABASE_PATH

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

CREATE TABLE IF NOT EXISTS funds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    percentage REAL NOT NULL DEFAULT 0,
    description TEXT,
    override_balance REAL DEFAULT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS fund_categories (
    fund_id INTEGER NOT NULL,
    category TEXT NOT NULL,
    PRIMARY KEY (fund_id, category),
    FOREIGN KEY (fund_id) REFERENCES funds(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS salary_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    year_month TEXT NOT NULL UNIQUE,
    amount REAL NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS bonus_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    year_month TEXT NOT NULL,
    amount REAL NOT NULL,
    note TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS fund_balance_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fund_id INTEGER NOT NULL,
    type TEXT NOT NULL CHECK(type IN ('topup', 'manual')),
    date TEXT NOT NULL,
    amount REAL NOT NULL,
    note TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (fund_id) REFERENCES funds(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS savings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    principal REAL NOT NULL,
    annual_rate REAL NOT NULL,
    term_months INTEGER NOT NULL,
    start_date TEXT NOT NULL,
    rollover_type TEXT NOT NULL DEFAULT 'withdraw' CHECK(rollover_type IN ('withdraw', 'rollover_principal', 'rollover_full')),
    saving_type TEXT NOT NULL DEFAULT 'fixed' CHECK(saving_type IN ('fixed', 'flexible')),
    fund_id INTEGER REFERENCES funds(id) ON DELETE SET NULL,
    note TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS saving_withdrawals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    saving_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    amount REAL NOT NULL,
    note TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (saving_id) REFERENCES savings(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS extra_fees (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    statuses TEXT NOT NULL DEFAULT '',
    total_amount REAL DEFAULT NULL,
    deadline TEXT DEFAULT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS extra_fee_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fee_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    amount REAL NOT NULL,
    name TEXT NOT NULL,
    note TEXT,
    status TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (fee_id) REFERENCES extra_fees(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_fee_entries_fee ON extra_fee_entries(fee_id);
CREATE INDEX IF NOT EXISTS idx_fee_entries_date ON extra_fee_entries(date);

CREATE TABLE IF NOT EXISTS investments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    unit TEXT NOT NULL DEFAULT 'VND',
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS investment_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    investment_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    amount REAL NOT NULL,
    note TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (investment_id) REFERENCES investments(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_inv_items_inv ON investment_items(investment_id);
CREATE INDEX IF NOT EXISTS idx_inv_items_date ON investment_items(date);

CREATE TABLE IF NOT EXISTS pays (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS pay_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pay_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    amount REAL NOT NULL,
    note TEXT,
    paid INTEGER NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (pay_id) REFERENCES pays(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_pay_items_pay ON pay_items(pay_id);
CREATE INDEX IF NOT EXISTS idx_pay_items_date ON pay_items(date);

CREATE TABLE IF NOT EXISTS assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    amount REAL NOT NULL DEFAULT 0,
    unit TEXT NOT NULL DEFAULT 'VND',
    created_at TEXT DEFAULT (datetime('now'))
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
    existing_fund_cols = {
        row[1] for row in conn.execute("PRAGMA table_info(funds)").fetchall()
        if conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='funds'").fetchone()
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
    if existing_fund_cols and "override_balance" not in existing_fund_cols:
        migrations.append("ALTER TABLE funds ADD COLUMN override_balance REAL DEFAULT NULL")

    # Create fund_balance_log if it doesn't exist (new table, use CREATE IF NOT EXISTS)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS fund_balance_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fund_id INTEGER NOT NULL,
            type TEXT NOT NULL CHECK(type IN ('topup', 'manual')),
            date TEXT NOT NULL,
            amount REAL NOT NULL,
            note TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (fund_id) REFERENCES funds(id) ON DELETE CASCADE
        )
    """)

    # Create savings table if it doesn't exist
    conn.execute("""
        CREATE TABLE IF NOT EXISTS savings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            principal REAL NOT NULL,
            annual_rate REAL NOT NULL,
            term_months INTEGER NOT NULL,
            start_date TEXT NOT NULL,
            rollover_type TEXT NOT NULL DEFAULT 'withdraw' CHECK(rollover_type IN ('withdraw', 'rollover_principal', 'rollover_full')),
            saving_type TEXT NOT NULL DEFAULT 'fixed' CHECK(saving_type IN ('fixed', 'flexible')),
            fund_id INTEGER REFERENCES funds(id) ON DELETE SET NULL,
            note TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    # Add saving_withdrawals table if it doesn't exist
    conn.execute("""
        CREATE TABLE IF NOT EXISTS saving_withdrawals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            saving_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            amount REAL NOT NULL,
            note TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (saving_id) REFERENCES savings(id) ON DELETE CASCADE
        )
    """)
    # Add new columns to existing savings table if missing
    existing_saving_cols = {
        row[1] for row in conn.execute("PRAGMA table_info(savings)").fetchall()
        if conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='savings'").fetchone()
    }
    if existing_saving_cols and "rollover_type" not in existing_saving_cols:
        conn.execute("ALTER TABLE savings ADD COLUMN rollover_type TEXT NOT NULL DEFAULT 'withdraw'")
    if existing_saving_cols and "fund_id" not in existing_saving_cols:
        conn.execute("ALTER TABLE savings ADD COLUMN fund_id INTEGER REFERENCES funds(id) ON DELETE SET NULL")
    if existing_saving_cols and "saving_type" not in existing_saving_cols:
        conn.execute("ALTER TABLE savings ADD COLUMN saving_type TEXT NOT NULL DEFAULT 'fixed'")

    # Create settings table if it doesn't exist
    conn.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    # Create extra_fees and extra_fee_entries tables if they don't exist
    conn.execute("""
        CREATE TABLE IF NOT EXISTS extra_fees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            statuses TEXT NOT NULL DEFAULT '',
            total_amount REAL DEFAULT NULL,
            deadline TEXT DEFAULT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS extra_fee_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fee_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            amount REAL NOT NULL,
            name TEXT NOT NULL,
            note TEXT,
            status TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (fee_id) REFERENCES extra_fees(id) ON DELETE CASCADE
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_fee_entries_fee ON extra_fee_entries(fee_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_fee_entries_date ON extra_fee_entries(date)")

    existing_fee_cols = {
        row[1] for row in conn.execute("PRAGMA table_info(extra_fees)").fetchall()
        if conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='extra_fees'").fetchone()
    }
    if existing_fee_cols and "deadline" not in existing_fee_cols:
        conn.execute("ALTER TABLE extra_fees ADD COLUMN deadline TEXT DEFAULT NULL")

    # Create investments and investment_items tables if they don't exist
    conn.execute("""
        CREATE TABLE IF NOT EXISTS investments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            description TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS investment_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            investment_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            amount REAL NOT NULL,
            note TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (investment_id) REFERENCES investments(id) ON DELETE CASCADE
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_inv_items_inv ON investment_items(investment_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_inv_items_date ON investment_items(date)")

    existing_inv_cols = {
        row[1] for row in conn.execute("PRAGMA table_info(investments)").fetchall()
        if conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='investments'").fetchone()
    }
    if existing_inv_cols and "unit" not in existing_inv_cols:
        conn.execute("ALTER TABLE investments ADD COLUMN unit TEXT NOT NULL DEFAULT 'VND'")

    # Create pays and pay_items tables if they don't exist
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pays (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            description TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pay_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pay_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            amount REAL NOT NULL,
            note TEXT,
            paid INTEGER NOT NULL DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (pay_id) REFERENCES pays(id) ON DELETE CASCADE
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pay_items_pay ON pay_items(pay_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pay_items_date ON pay_items(date)")

    # Create assets table if it doesn't exist
    conn.execute("""
        CREATE TABLE IF NOT EXISTS assets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            description TEXT,
            amount REAL NOT NULL DEFAULT 0,
            unit TEXT NOT NULL DEFAULT 'VND',
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)

    # Create bonus_entries table if it doesn't exist
    conn.execute("""
        CREATE TABLE IF NOT EXISTS bonus_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            year_month TEXT NOT NULL,
            amount REAL NOT NULL,
            note TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)

    for sql in migrations:
        conn.execute(sql)
