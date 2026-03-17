"""Repository for CRUD operations and queries on statement/transaction data."""

from __future__ import annotations

import sqlite3
from datetime import date
from decimal import Decimal
from typing import Any

from techcombank_parser.database.db import init_db
from techcombank_parser.models.transaction import (
    ParseResult,
    StatementMetadata,
    StatementType,
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
               (source_file, statement_type, statement_date, due_date, card_number_masked,
                card_holder_name, total_due, min_payment, credit_limit,
                period_start, period_end, account_number, opening_balance,
                ending_balance, page_count, parse_method)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                meta.source_file or "unknown",
                meta.statement_type.value,
                _date_str(meta.statement_date),
                _date_str(meta.due_date),
                meta.card_number_masked,
                meta.card_holder_name,
                _decimal_str(meta.total_due),
                _decimal_str(meta.min_payment),
                _decimal_str(meta.credit_limit),
                _date_str(meta.statement_period_start),
                _date_str(meta.statement_period_end),
                meta.account_number,
                _decimal_str(meta.opening_balance),
                _decimal_str(meta.ending_balance),
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
                    reference_number, running_balance)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                    _decimal_str(txn.running_balance),
                ),
            )

        self.conn.commit()

        # Auto-assign categories from previously categorized merchants
        self.conn.execute(
            """UPDATE transactions
               SET category = (
                   SELECT t2.category FROM transactions t2
                   WHERE t2.merchant_name = transactions.merchant_name
                     AND t2.category IS NOT NULL AND t2.category != ''
                     AND t2.id != transactions.id
                   LIMIT 1
               )
               WHERE statement_id = ?
                 AND (category IS NULL OR category = '')
                 AND merchant_name IS NOT NULL""",
            (statement_id,),
        )
        self.conn.commit()

        # Apply category rules to remaining uncategorized
        self.apply_rules(statement_id=statement_id)

        return statement_id

    def get_transactions(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        transaction_type: str | None = None,
        category: str | None = None,
        search: str | None = None,
        statement_id: int | None = None,
        statement_type: str | None = None,
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
        if statement_type:
            conditions.append("s.statement_type = ?")
            params.append(statement_type)
        if search:
            conditions.append("t.description LIKE ?")
            params.append(f"%{search}%")

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        rows = self.conn.execute(
            f"""SELECT t.*, s.source_file, s.statement_date as stmt_date,
                       s.statement_type
                FROM transactions t
                JOIN statements s ON t.statement_id = s.id
                {where}
                ORDER BY t.transaction_date DESC
                LIMIT ? OFFSET ?""",
            params + [limit, offset],
        ).fetchall()

        return [dict(row) for row in rows]

    def get_spending_summary(self, statement_id: int | None = None, category: str | None = None, statement_type: str | None = None, start_date: str | None = None, end_date: str | None = None) -> dict[str, Any]:
        """Get aggregate spending summary."""
        conditions: list[str] = []
        params: list[Any] = []
        if start_date:
            conditions.append("t.transaction_date >= ?")
            params.append(start_date)
        if end_date:
            conditions.append("t.transaction_date <= ?")
            params.append(end_date)
        if statement_id:
            conditions.append("t.statement_id = ?")
            params.append(statement_id)
        if statement_type:
            conditions.append("s.statement_type = ?")
            params.append(statement_type)
        if category == "__uncategorized__":
            conditions.append("(t.category IS NULL OR t.category = '')")
        elif category:
            conditions.append("t.category = ?")
            params.append(category)

        join = "JOIN statements s ON t.statement_id = s.id"
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        row = self.conn.execute(
            f"""SELECT
                COUNT(*) as total_transactions,
                SUM(CASE WHEN t.transaction_type='debit' THEN CAST(t.billing_amount_vnd AS REAL) ELSE 0 END) as total_debit,
                SUM(CASE WHEN t.transaction_type='credit' THEN CAST(t.billing_amount_vnd AS REAL) ELSE 0 END) as total_credit
               FROM transactions t {join} {where}""",
            params,
        ).fetchone()

        monthly = self.conn.execute(
            f"""SELECT
                substr(t.transaction_date, 1, 7) as month,
                SUM(CASE WHEN t.transaction_type='debit' THEN CAST(t.billing_amount_vnd AS REAL) ELSE 0 END) as spending,
                SUM(CASE WHEN t.transaction_type='credit' THEN CAST(t.billing_amount_vnd AS REAL) ELSE 0 END) as income,
                COUNT(*) as count
               FROM transactions t {join} {where}
               GROUP BY substr(t.transaction_date, 1, 7)
               ORDER BY month""",
            params,
        ).fetchall()

        yearly = self.conn.execute(
            f"""SELECT
                substr(t.transaction_date, 1, 4) as year,
                SUM(CASE WHEN t.transaction_type='debit' THEN CAST(t.billing_amount_vnd AS REAL) ELSE 0 END) as spending,
                COUNT(*) as count
               FROM transactions t {join} {where}
               GROUP BY substr(t.transaction_date, 1, 4)
               ORDER BY year""",
            params,
        ).fetchall()

        return {
            "total_transactions": row["total_transactions"],
            "total_debit": row["total_debit"] or 0,
            "total_credit": row["total_credit"] or 0,
            "monthly": [dict(m) for m in monthly],
            "yearly": [dict(y) for y in yearly],
        }

    def get_statements(self, start_date: str | None = None, end_date: str | None = None) -> list[dict[str, Any]]:
        """List all imported statements, optionally filtered to those with transactions in the date range."""
        conditions: list[str] = []
        params: list[Any] = []
        if start_date:
            conditions.append("t.transaction_date >= ?")
            params.append(start_date)
        if end_date:
            conditions.append("t.transaction_date <= ?")
            params.append(end_date)
        having = "HAVING COUNT(t.id) > 0" if conditions else ""
        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        rows = self.conn.execute(
            f"""SELECT s.*,
                COUNT(t.id) as transaction_count
               FROM statements s
               LEFT JOIN transactions t ON s.id = t.statement_id {where}
               GROUP BY s.id
               {having}
               ORDER BY s.statement_date DESC""",
            params,
        ).fetchall()
        return [dict(row) for row in rows]

    def get_transaction_count(
        self,
        statement_id: int | None = None,
        category: str | None = None,
        search: str | None = None,
        statement_type: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> int:
        """Get total number of transactions matching filters."""
        conditions: list[str] = []
        params: list[Any] = []
        if start_date:
            conditions.append("t.transaction_date >= ?")
            params.append(start_date)
        if end_date:
            conditions.append("t.transaction_date <= ?")
            params.append(end_date)
        if statement_id:
            conditions.append("t.statement_id = ?")
            params.append(statement_id)
        if statement_type:
            conditions.append("s.statement_type = ?")
            params.append(statement_type)
        if category == "__uncategorized__":
            conditions.append("(t.category IS NULL OR t.category = '')")
        elif category:
            conditions.append("t.category = ?")
            params.append(category)
        if search:
            conditions.append("t.description LIKE ?")
            params.append(f"%{search}%")
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        row = self.conn.execute(
            f"""SELECT COUNT(*) as cnt
                FROM transactions t
                JOIN statements s ON t.statement_id = s.id
                {where}""",
            params,
        ).fetchone()
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

    def get_available_years_months(self) -> list[str]:
        """Return available year-month values sorted descending, e.g. ['2026-02', '2026-01', ...]."""
        rows = self.conn.execute(
            """SELECT DISTINCT substr(transaction_date,1,7) as ym
               FROM transactions ORDER BY ym DESC"""
        ).fetchall()
        return [row["ym"] for row in rows]

    def get_all_categories(self, statement_id: int | None = None, statement_type: str | None = None, start_date: str | None = None, end_date: str | None = None) -> list[str]:
        """Get all distinct non-null categories, optionally filtered."""
        conditions = ["t.category IS NOT NULL", "t.category != ''"]
        params: list[Any] = []
        if start_date:
            conditions.append("t.transaction_date >= ?")
            params.append(start_date)
        if end_date:
            conditions.append("t.transaction_date <= ?")
            params.append(end_date)
        if statement_id:
            conditions.append("t.statement_id = ?")
            params.append(statement_id)
        if statement_type:
            conditions.append("s.statement_type = ?")
            params.append(statement_type)
        where = "WHERE " + " AND ".join(conditions)
        join = "JOIN statements s ON t.statement_id = s.id" if statement_type else ""
        rows = self.conn.execute(
            f"SELECT DISTINCT t.category FROM transactions t {join} {where} ORDER BY t.category",
            params,
        ).fetchall()
        return [row["category"] for row in rows]

    def get_category_monthly_summary(self, statement_id: int | None = None, category: str | None = None, statement_type: str | None = None, start_date: str | None = None, end_date: str | None = None) -> dict[str, Any]:
        """Get spending by category per month (debit only)."""
        conditions = ["t.transaction_type = 'debit'"]
        params: list[Any] = []
        if start_date:
            conditions.append("t.transaction_date >= ?")
            params.append(start_date)
        if end_date:
            conditions.append("t.transaction_date <= ?")
            params.append(end_date)
        if statement_id:
            conditions.append("t.statement_id = ?")
            params.append(statement_id)
        if statement_type:
            conditions.append("s.statement_type = ?")
            params.append(statement_type)
        if category == "__uncategorized__":
            conditions.append("(t.category IS NULL OR t.category = '')")
        elif category:
            conditions.append("t.category = ?")
            params.append(category)

        where = "WHERE " + " AND ".join(conditions)

        rows = self.conn.execute(
            f"""SELECT
                substr(t.transaction_date, 1, 7) as month,
                COALESCE(t.category, '') as cat,
                SUM(CAST(t.billing_amount_vnd AS REAL)) as spending,
                COUNT(*) as txn_count
               FROM transactions t
               JOIN statements s ON t.statement_id = s.id
               {where}
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

    # ── Category Rules ──

    def get_rules(self) -> list[dict[str, Any]]:
        """Get all category rules ordered by priority (highest first)."""
        rows = self.conn.execute(
            "SELECT * FROM category_rules ORDER BY priority DESC, id"
        ).fetchall()
        return [dict(row) for row in rows]

    def add_rule(self, match_type: str, pattern: str, category: str, priority: int = 0) -> int:
        """Add a category rule. Returns the rule ID."""
        cursor = self.conn.execute(
            """INSERT OR REPLACE INTO category_rules (match_type, pattern, category, priority)
               VALUES (?, ?, ?, ?)""",
            (match_type, pattern.strip(), category.strip(), priority),
        )
        self.conn.commit()
        return cursor.lastrowid

    def update_rule(self, rule_id: int, category: str) -> bool:
        """Update the category of a rule. Returns True if updated."""
        cursor = self.conn.execute(
            "UPDATE category_rules SET category = ? WHERE id = ?",
            (category.strip(), rule_id),
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def delete_rule(self, rule_id: int) -> bool:
        """Delete a category rule. Returns True if deleted."""
        cursor = self.conn.execute("DELETE FROM category_rules WHERE id = ?", (rule_id,))
        self.conn.commit()
        return cursor.rowcount > 0

    def apply_rules(self, statement_id: int | None = None) -> int:
        """Apply all category rules to uncategorized transactions.

        Rules are applied in priority order (highest first). Only updates
        transactions that have no category set.

        Returns the number of transactions updated.
        """
        rules = self.get_rules()
        if not rules:
            return 0

        total_updated = 0
        stmt_filter = "AND statement_id = ?" if statement_id else ""
        stmt_params = [statement_id] if statement_id else []

        for rule in rules:
            match_type = rule["match_type"]
            pattern = rule["pattern"]
            category = rule["category"]

            if match_type == "contains":
                condition = "description LIKE ?"
                param = f"%{pattern}%"
            elif match_type == "endswith":
                condition = "description LIKE ?"
                param = f"%{pattern}"
            else:
                continue

            cursor = self.conn.execute(
                f"""UPDATE transactions
                    SET category = ?
                    WHERE (category IS NULL OR category = '')
                      AND {condition}
                      {stmt_filter}""",
                [category, param] + stmt_params,
            )
            total_updated += cursor.rowcount

        self.conn.commit()
        return total_updated


def _date_str(d: date | None) -> str | None:
    return d.isoformat() if d else None


def _decimal_str(d: Decimal | None) -> str | None:
    return str(d) if d else None
