"""Repository for CRUD operations and queries on statement/transaction data."""

from __future__ import annotations

import sqlite3
from datetime import date
from decimal import Decimal
from typing import Any

from techcombank_pdf.database.db import init_db
from techcombank_pdf.models.transaction import (
    ParseResult,
    StatementMetadata,
    Transaction,
    TransactionType,
)


class Repository:
    """Database repository for statements and transactions."""

    def __init__(self, db_path: str | None = None):
        self.conn = init_db(db_path)

    def close(self):
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def import_parse_result(self, result: ParseResult) -> int:
        """Import a ParseResult into the database. Returns the statement ID.

        Uses INSERT OR REPLACE for idempotent imports.
        """
        meta = result.metadata
        cursor = self.conn.execute(
            """INSERT OR REPLACE INTO statements
               (source_file, statement_date, due_date, card_number_masked,
                card_holder_name, total_due, min_payment, credit_limit,
                period_start, period_end, page_count, parse_method)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                meta.source_file or "unknown",
                _date_str(meta.statement_date),
                _date_str(meta.due_date),
                meta.card_number_masked,
                meta.card_holder_name,
                _decimal_str(meta.total_due),
                _decimal_str(meta.min_payment),
                _decimal_str(meta.credit_limit),
                _date_str(meta.statement_period_start),
                _date_str(meta.statement_period_end),
                result.page_count,
                result.parse_method,
            ),
        )
        statement_id = cursor.lastrowid

        # Delete existing transactions for this statement (for re-import)
        self.conn.execute(
            "DELETE FROM transactions WHERE statement_id = ?", (statement_id,)
        )

        # Insert transactions
        for txn in result.transactions:
            self.conn.execute(
                """INSERT INTO transactions
                   (statement_id, transaction_date, posting_date, description,
                    original_amount, original_currency, billing_amount_vnd,
                    transaction_type, category, merchant_name, card_last_four,
                    reference_number)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    statement_id,
                    _date_str(txn.transaction_date),
                    _date_str(txn.posting_date),
                    txn.description,
                    str(txn.original_amount),
                    txn.original_currency,
                    str(txn.billing_amount_vnd),
                    txn.transaction_type.value,
                    txn.category,
                    txn.merchant_name,
                    txn.card_last_four,
                    txn.reference_number,
                ),
            )

        self.conn.commit()
        return statement_id

    def get_transactions(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        transaction_type: str | None = None,
        search: str | None = None,
        limit: int = 500,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Query transactions with optional filters."""
        conditions: list[str] = []
        params: list[Any] = []

        if start_date:
            conditions.append("t.transaction_date >= ?")
            params.append(start_date)
        if end_date:
            conditions.append("t.transaction_date <= ?")
            params.append(end_date)
        if transaction_type:
            conditions.append("t.transaction_type = ?")
            params.append(transaction_type)
        if search:
            conditions.append("t.description LIKE ?")
            params.append(f"%{search}%")

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        rows = self.conn.execute(
            f"""SELECT t.*, s.source_file, s.statement_date as stmt_date
                FROM transactions t
                JOIN statements s ON t.statement_id = s.id
                {where}
                ORDER BY t.transaction_date DESC
                LIMIT ? OFFSET ?""",
            params + [limit, offset],
        ).fetchall()

        return [dict(row) for row in rows]

    def get_spending_summary(self) -> dict[str, Any]:
        """Get aggregate spending summary."""
        row = self.conn.execute(
            """SELECT
                COUNT(*) as total_transactions,
                SUM(CASE WHEN transaction_type='debit' THEN CAST(billing_amount_vnd AS REAL) ELSE 0 END) as total_debit,
                SUM(CASE WHEN transaction_type='credit' THEN CAST(billing_amount_vnd AS REAL) ELSE 0 END) as total_credit
               FROM transactions"""
        ).fetchone()

        monthly = self.conn.execute(
            """SELECT
                substr(transaction_date, 1, 7) as month,
                SUM(CASE WHEN transaction_type='debit' THEN CAST(billing_amount_vnd AS REAL) ELSE 0 END) as spending,
                COUNT(*) as count
               FROM transactions
               GROUP BY substr(transaction_date, 1, 7)
               ORDER BY month"""
        ).fetchall()

        return {
            "total_transactions": row["total_transactions"],
            "total_debit": row["total_debit"] or 0,
            "total_credit": row["total_credit"] or 0,
            "monthly": [dict(m) for m in monthly],
        }

    def get_statements(self) -> list[dict[str, Any]]:
        """List all imported statements."""
        rows = self.conn.execute(
            """SELECT s.*,
                COUNT(t.id) as transaction_count
               FROM statements s
               LEFT JOIN transactions t ON s.id = t.statement_id
               GROUP BY s.id
               ORDER BY s.statement_date DESC"""
        ).fetchall()
        return [dict(row) for row in rows]

    def get_transaction_count(self) -> int:
        """Get total number of transactions."""
        row = self.conn.execute("SELECT COUNT(*) as cnt FROM transactions").fetchone()
        return row["cnt"]


def _date_str(d: date | None) -> str | None:
    return d.isoformat() if d else None


def _decimal_str(d: Decimal | None) -> str | None:
    return str(d) if d else None
