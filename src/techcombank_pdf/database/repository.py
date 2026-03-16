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
        category: str | None = None,
        search: str | None = None,
        statement_id: int | None = None,
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
        if category == "__uncategorized__":
            conditions.append("(t.category IS NULL OR t.category = '')")
        elif category:
            conditions.append("t.category = ?")
            params.append(category)
        if statement_id:
            conditions.append("t.statement_id = ?")
            params.append(statement_id)
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

    def get_spending_summary(self, statement_id: int | None = None) -> dict[str, Any]:
        """Get aggregate spending summary."""
        where = "WHERE statement_id = ?" if statement_id else ""
        params = [statement_id] if statement_id else []

        row = self.conn.execute(
            f"""SELECT
                COUNT(*) as total_transactions,
                SUM(CASE WHEN transaction_type='debit' THEN CAST(billing_amount_vnd AS REAL) ELSE 0 END) as total_debit,
                SUM(CASE WHEN transaction_type='credit' THEN CAST(billing_amount_vnd AS REAL) ELSE 0 END) as total_credit
               FROM transactions {where}""",
            params,
        ).fetchone()

        monthly = self.conn.execute(
            f"""SELECT
                substr(transaction_date, 1, 7) as month,
                SUM(CASE WHEN transaction_type='debit' THEN CAST(billing_amount_vnd AS REAL) ELSE 0 END) as spending,
                COUNT(*) as count
               FROM transactions {where}
               GROUP BY substr(transaction_date, 1, 7)
               ORDER BY month""",
            params,
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

    def get_transaction_count(self, statement_id: int | None = None) -> int:
        """Get total number of transactions."""
        if statement_id:
            row = self.conn.execute(
                "SELECT COUNT(*) as cnt FROM transactions WHERE statement_id = ?",
                (statement_id,),
            ).fetchone()
        else:
            row = self.conn.execute("SELECT COUNT(*) as cnt FROM transactions").fetchone()
        return row["cnt"]

    def update_transaction_category(self, txn_id: int, category: str | None) -> bool:
        """Update the category of a transaction. Returns True if updated."""
        cursor = self.conn.execute(
            "UPDATE transactions SET category = ? WHERE id = ?",
            (category or None, txn_id),
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def update_category_by_merchant(self, merchant_name: str, category: str | None) -> int:
        """Update category for all transactions with the same merchant_name.

        Returns the number of rows updated.
        """
        cursor = self.conn.execute(
            "UPDATE transactions SET category = ? WHERE merchant_name = ?",
            (category or None, merchant_name),
        )
        self.conn.commit()
        return cursor.rowcount

    def get_all_categories(self) -> list[str]:
        """Get all distinct non-null categories."""
        rows = self.conn.execute(
            "SELECT DISTINCT category FROM transactions WHERE category IS NOT NULL AND category != '' ORDER BY category"
        ).fetchall()
        return [row["category"] for row in rows]

    def get_category_monthly_summary(self, statement_id: int | None = None) -> dict[str, Any]:
        """Get spending by category per month (debit only).

        Returns:
            {
                "months": ["2026-01", "2026-02"],
                "categories": [
                    {"name": "Food", "monthly": {"2026-01": 500000, "2026-02": 300000}, "total": 800000},
                    ...
                ],
                "uncategorized": {"monthly": {...}, "total": ...}
            }
        """
        where = "AND statement_id = ?" if statement_id else ""
        params: list[Any] = [statement_id] if statement_id else []

        rows = self.conn.execute(
            f"""SELECT
                substr(transaction_date, 1, 7) as month,
                COALESCE(category, '') as cat,
                SUM(CAST(billing_amount_vnd AS REAL)) as spending,
                COUNT(*) as txn_count
               FROM transactions
               WHERE transaction_type = 'debit' {where}
               GROUP BY month, cat
               ORDER BY month, cat""",
            params,
        ).fetchall()

        months_set: set[str] = set()
        cat_data: dict[str, dict[str, float]] = {}
        cat_counts: dict[str, int] = {}

        for row in rows:
            month = row["month"]
            cat = row["cat"] or ""
            months_set.add(month)
            if cat not in cat_data:
                cat_data[cat] = {}
                cat_counts[cat] = 0
            cat_data[cat][month] = row["spending"]
            cat_counts[cat] += row["txn_count"]

        months = sorted(months_set)

        categories = []
        uncategorized = {"monthly": {}, "total": 0.0, "count": 0}

        for cat, monthly in sorted(cat_data.items()):
            total = sum(monthly.values())
            entry = {"name": cat, "monthly": monthly, "total": total, "count": cat_counts[cat]}
            if cat == "":
                uncategorized = {"monthly": monthly, "total": total, "count": cat_counts[cat]}
            else:
                categories.append(entry)

        # Sort by total descending
        categories.sort(key=lambda c: c["total"], reverse=True)

        return {
            "months": months,
            "categories": categories,
            "uncategorized": uncategorized,
        }


def _date_str(d: date | None) -> str | None:
    return d.isoformat() if d else None


def _decimal_str(d: Decimal | None) -> str | None:
    return str(d) if d else None
