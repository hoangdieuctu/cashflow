"""Repository for CRUD operations and queries on statement/transaction data."""

from __future__ import annotations

import sqlite3
from datetime import date
from decimal import Decimal
from typing import Any

from cashflow.database.db import init_db
from cashflow.models.transaction import (
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

    # ── Funds ──

    def get_funds(self) -> list[dict[str, Any]]:
        """Get all funds with their assigned categories."""
        funds = [dict(r) for r in self.conn.execute(
            "SELECT * FROM funds ORDER BY percentage DESC, name"
        ).fetchall()]
        for fund in funds:
            rows = self.conn.execute(
                "SELECT category FROM fund_categories WHERE fund_id = ? ORDER BY category",
                (fund["id"],),
            ).fetchall()
            fund["categories"] = [r["category"] for r in rows]
        return funds

    def add_fund(self, name: str, percentage: float, description: str = "") -> int:
        cursor = self.conn.execute(
            "INSERT INTO funds (name, percentage, description) VALUES (?, ?, ?)",
            (name.strip(), percentage, description.strip()),
        )
        self.conn.commit()
        return cursor.lastrowid

    def update_fund(self, fund_id: int, name: str | None = None, percentage: float | None = None, description: str | None = None, override_balance: float | None | bool = False, override_reason: str | None = None) -> bool:
        fields, params = [], []
        if name is not None:
            fields.append("name = ?"); params.append(name.strip())
        if percentage is not None:
            fields.append("percentage = ?"); params.append(percentage)
        if description is not None:
            fields.append("description = ?"); params.append(description.strip())
        # override_balance=False means "not provided"; None means "clear it"; float means "set it"
        if override_balance is not False:
            fields.append("override_balance = ?"); params.append(override_balance)
        if not fields:
            return False
        # Write manual balance log entry if override_balance is being set
        if override_balance is not False and override_balance is not None:
            from datetime import date as _date
            note = override_reason or "Manual balance set"
            self.conn.execute(
                """INSERT INTO fund_balance_log (fund_id, type, date, amount, note)
                   VALUES (?, 'manual', ?, ?, ?)""",
                (fund_id, _date.today().isoformat(), override_balance, note),
            )
        params.append(fund_id)
        cursor = self.conn.execute(f"UPDATE funds SET {', '.join(fields)} WHERE id = ?", params)
        self.conn.commit()
        return cursor.rowcount > 0

    def delete_fund(self, fund_id: int) -> bool:
        cursor = self.conn.execute("DELETE FROM funds WHERE id = ?", (fund_id,))
        self.conn.commit()
        return cursor.rowcount > 0

    def set_fund_categories(self, fund_id: int, categories: list[str]) -> None:
        """Replace all categories assigned to a fund.
        Each category can only belong to one fund — removes it from any other fund first.
        """
        self.conn.execute("DELETE FROM fund_categories WHERE fund_id = ?", (fund_id,))
        for cat in categories:
            cat = cat.strip()
            # Remove from any other fund first
            self.conn.execute(
                "DELETE FROM fund_categories WHERE category = ? AND fund_id != ?",
                (cat, fund_id),
            )
            self.conn.execute(
                "INSERT OR IGNORE INTO fund_categories (fund_id, category) VALUES (?, ?)",
                (fund_id, cat),
            )
        self.conn.commit()

    def get_fund_chart_data(self, start_date: str | None = None, end_date: str | None = None) -> dict[str, Any]:
        """Return per-fund spending data for dashboard charts.

        Returns:
          funds: list of {name, allocated, spent, balance} using the given date range for spent.
          monthly: list of {month, <fund_name>: amount, ...} for stacked bar chart.
        """
        funds = self.get_funds()
        salary_entries = self.get_salary_entries()
        total_salary = sum(e["amount"] for e in salary_entries)

        fund_results = []
        for fund in funds:
            pct = fund["percentage"] / 100.0
            allocated = total_salary * pct
            cats = fund["categories"]
            if cats:
                placeholders = ",".join("?" * len(cats))
                conditions = [f"transaction_type = 'debit'", f"category IN ({placeholders})"]
                params: list[Any] = list(cats)
                if start_date:
                    conditions.append("transaction_date >= ?")
                    params.append(start_date)
                if end_date:
                    conditions.append("transaction_date <= ?")
                    params.append(end_date)
                where = "WHERE " + " AND ".join(conditions)
                row = self.conn.execute(
                    f"SELECT COALESCE(SUM(CAST(billing_amount_vnd AS REAL)), 0) as total FROM transactions {where}",
                    params,
                ).fetchone()
                spent = row["total"]
            else:
                spent = 0.0
            fund_results.append({"name": fund["name"], "allocated": allocated, "spent": spent})

        # Monthly breakdown per fund
        # Get all months in range
        month_conditions = []
        month_params: list[Any] = []
        if start_date:
            month_conditions.append("transaction_date >= ?")
            month_params.append(start_date)
        if end_date:
            month_conditions.append("transaction_date <= ?")
            month_params.append(end_date)
        base_where = ("WHERE " + " AND ".join(month_conditions)) if month_conditions else ""

        all_months_rows = self.conn.execute(
            f"SELECT DISTINCT substr(transaction_date,1,7) as ym FROM transactions {base_where} ORDER BY ym",
            month_params,
        ).fetchall()
        all_months = [r["ym"] for r in all_months_rows]

        monthly: dict[str, dict[str, float]] = {m: {} for m in all_months}
        for fund in funds:
            cats = fund["categories"]
            if not cats:
                continue
            placeholders = ",".join("?" * len(cats))
            conditions = [f"transaction_type = 'debit'", f"category IN ({placeholders})"]
            params = list(cats)
            if start_date:
                conditions.append("transaction_date >= ?")
                params.append(start_date)
            if end_date:
                conditions.append("transaction_date <= ?")
                params.append(end_date)
            where = "WHERE " + " AND ".join(conditions)
            rows = self.conn.execute(
                f"""SELECT substr(transaction_date,1,7) as ym,
                           SUM(CAST(billing_amount_vnd AS REAL)) as total
                    FROM transactions {where}
                    GROUP BY ym""",
                params,
            ).fetchall()
            for r in rows:
                if r["ym"] in monthly:
                    monthly[r["ym"]][fund["name"]] = r["total"]

        monthly_list = [{"month": m, **monthly[m]} for m in all_months]

        return {"funds": fund_results, "monthly": monthly_list}

    # ── Salary entries ──

    def get_salary_entries(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM salary_entries ORDER BY year_month DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def add_salary_entry(self, year_month: str, amount: float) -> int:
        cursor = self.conn.execute(
            "INSERT OR REPLACE INTO salary_entries (year_month, amount) VALUES (?, ?)",
            (year_month, amount),
        )
        entry_id = cursor.lastrowid
        # Write topup log entries for all existing funds
        funds = self.get_funds()
        for fund in funds:
            topup = amount * (fund["percentage"] / 100.0)
            self.conn.execute(
                """INSERT INTO fund_balance_log (fund_id, type, date, amount, note)
                   VALUES (?, 'topup', ?, ?, ?)""",
                (fund["id"], year_month + "-01", topup, f"Salary {year_month}"),
            )
            # If fund has a manual override balance, add the topup to it so salary
            # continues accumulating from the last reconciled snapshot
            if fund.get("override_balance") is not None:
                new_balance = fund["override_balance"] + topup
                self.conn.execute(
                    "UPDATE funds SET override_balance = ? WHERE id = ?",
                    (new_balance, fund["id"]),
                )
        self.conn.commit()
        return entry_id

    def delete_salary_entry(self, entry_id: int) -> bool:
        cursor = self.conn.execute("DELETE FROM salary_entries WHERE id = ?", (entry_id,))
        self.conn.commit()
        return cursor.rowcount > 0

    def get_fund_balances(self, year_month: str | None = None) -> list[dict[str, Any]]:
        """Calculate running balance for each fund.

        Balance = sum of (salary × percentage/100) for all salary entries
                  minus sum of debit transactions in assigned categories (all-time).
        Carry-over is implicit since we sum all time.

        year_month: if provided (YYYY-MM), filters only the `spent` value to that month.
                    allocated and balance always reflect all-time totals.
        """
        funds = self.get_funds()
        salary_entries = self.get_salary_entries()
        total_salary = sum(e["amount"] for e in salary_entries)

        # Per-month breakdown for top-ups
        salary_by_month = {e["year_month"]: e["amount"] for e in salary_entries}

        results = []
        for fund in funds:
            pct = fund["percentage"] / 100.0
            allocated = total_salary * pct

            # Sum debits for all categories assigned to this fund
            cats = fund["categories"]
            if cats:
                placeholders = ",".join("?" * len(cats))
                # all-time spent (for balance calculation)
                row = self.conn.execute(
                    f"""SELECT COALESCE(SUM(CAST(billing_amount_vnd AS REAL)), 0) as total
                        FROM transactions
                        WHERE transaction_type = 'debit'
                          AND category IN ({placeholders})""",
                    cats,
                ).fetchone()
                spent_alltime = row["total"]

                # period spent (for display, filtered by year_month if given)
                if year_month:
                    row2 = self.conn.execute(
                        f"""SELECT COALESCE(SUM(CAST(billing_amount_vnd AS REAL)), 0) as total
                            FROM transactions
                            WHERE transaction_type = 'debit'
                              AND category IN ({placeholders})
                              AND substr(transaction_date, 1, 7) = ?""",
                        cats + [year_month],
                    ).fetchone()
                    spent = row2["total"]
                else:
                    spent = spent_alltime
            else:
                spent = 0.0
                spent_alltime = 0.0

            # Monthly breakdown: top-ups and spending per month
            monthly = {}
            for ym, sal in salary_by_month.items():
                monthly[ym] = {"topup": sal * pct, "spent": 0.0}

            if cats:
                placeholders = ",".join("?" * len(cats))
                rows = self.conn.execute(
                    f"""SELECT substr(transaction_date, 1, 7) as ym,
                               SUM(CAST(billing_amount_vnd AS REAL)) as spent
                        FROM transactions
                        WHERE transaction_type = 'debit'
                          AND category IN ({placeholders})
                        GROUP BY ym""",
                    cats,
                ).fetchall()
                for r in rows:
                    if r["ym"] not in monthly:
                        monthly[r["ym"]] = {"topup": 0.0, "spent": 0.0}
                    monthly[r["ym"]]["spent"] = r["spent"]

            log_count = self.conn.execute(
                "SELECT COUNT(*) as cnt FROM fund_balance_log WHERE fund_id = ?",
                (fund["id"],),
            ).fetchone()["cnt"]

            # Sum principal of all savings linked to this fund (regardless of status)
            savings_principal = self.conn.execute(
                "SELECT COALESCE(SUM(principal), 0) as total FROM savings WHERE fund_id = ?",
                (fund["id"],),
            ).fetchone()["total"]

            savings_count = self.conn.execute(
                "SELECT COUNT(*) as cnt FROM savings WHERE fund_id = ?",
                (fund["id"],),
            ).fetchone()["cnt"]

            txn_count = 0
            if cats:
                placeholders = ",".join("?" * len(cats))
                if year_month:
                    txn_count = self.conn.execute(
                        f"SELECT COUNT(*) as cnt FROM transactions WHERE transaction_type='debit' AND category IN ({placeholders}) AND substr(transaction_date,1,7) = ?",
                        cats + [year_month],
                    ).fetchone()["cnt"]
                else:
                    txn_count = self.conn.execute(
                        f"SELECT COUNT(*) as cnt FROM transactions WHERE transaction_type='debit' AND category IN ({placeholders})",
                        cats,
                    ).fetchone()["cnt"]

            results.append({
                "id": fund["id"],
                "name": fund["name"],
                "percentage": fund["percentage"],
                "description": fund["description"],
                "override_balance": fund.get("override_balance"),
                "categories": cats,
                "allocated": allocated,
                "spent": spent,
                "balance": fund["override_balance"] if fund.get("override_balance") is not None else allocated - spent_alltime + savings_principal,
                "is_override": fund.get("override_balance") is not None,
                "history_count": log_count + txn_count + savings_count,
                "monthly": dict(sorted(monthly.items())),
            })

        return results

    def get_fund_history(self, fund_id: int, year_month: str | None = None) -> list[dict[str, Any]]:
        """Return combined history for a fund: topup/manual log + spending transactions, sorted by date desc.

        year_month: if provided (YYYY-MM), filters spend events to that month only.
                    topup and manual log entries are always included.
        """
        fund = next((f for f in self.get_funds() if f["id"] == fund_id), None)
        if not fund:
            return []

        events: list[dict[str, Any]] = []

        # Log entries (topup + manual) — always unfiltered
        rows = self.conn.execute(
            "SELECT * FROM fund_balance_log WHERE fund_id = ? ORDER BY date DESC, created_at DESC",
            (fund_id,),
        ).fetchall()
        for r in rows:
            events.append({
                "type": r["type"],
                "date": r["date"],
                "sort_key": r["created_at"],
                "amount": r["amount"],
                "note": r["note"],
            })

        # Spending transactions in assigned categories
        cats = fund["categories"]
        if cats:
            placeholders = ",".join("?" * len(cats))
            params: list[Any] = list(cats)
            ym_filter = ""
            if year_month:
                ym_filter = "AND substr(transaction_date, 1, 7) = ?"
                params.append(year_month)
            rows = self.conn.execute(
                f"""SELECT transaction_date, description, billing_amount_vnd, category
                    FROM transactions
                    WHERE transaction_type = 'debit' AND category IN ({placeholders})
                    {ym_filter}
                    ORDER BY transaction_date DESC""",
                params,
            ).fetchall()
            for r in rows:
                events.append({
                    "type": "spend",
                    "date": r["transaction_date"],
                    "sort_key": r["transaction_date"],
                    "amount": -float(r["billing_amount_vnd"]),
                    "note": r["description"],
                    "category": r["category"],
                })

        # Linked savings — always unfiltered (not month-scoped)
        import calendar as _cal
        def _add_months(d: date, m: int) -> date:
            yr = d.year + (d.month - 1 + m) // 12
            mo = (d.month - 1 + m) % 12 + 1
            dy = min(d.day, _cal.monthrange(yr, mo)[1])
            return date(yr, mo, dy)

        savings_rows = self.conn.execute(
            "SELECT name, principal, start_date, term_months FROM savings WHERE fund_id = ?",
            (fund_id,),
        ).fetchall()
        for r in savings_rows:
            start = date.fromisoformat(r["start_date"])
            maturity = _add_months(start, r["term_months"])
            events.append({
                "type": "saving",
                "date": r["start_date"],
                "sort_key": r["start_date"],
                "amount": r["principal"],
                "note": r["name"],
                "maturity_date": maturity.isoformat(),
            })

        events.sort(key=lambda e: (e["sort_key"], e["type"] != "manual"), reverse=True)
        for e in events:
            del e["sort_key"]
        return events

    def get_savings(self) -> list[dict[str, Any]]:
        """Get all savings entries with calculated fields.

        Fixed savings: interest = principal × rate/100 × actual_days / 365
        Flexible savings: interest calculated per segment between withdrawals.
        current_principal = original_principal - sum(withdrawals)
        """
        import calendar
        rows = self.conn.execute(
            """SELECT s.*, f.name AS fund_name
               FROM savings s
               LEFT JOIN funds f ON f.id = s.fund_id"""
        ).fetchall()
        results = []
        today = date.today()

        def add_months(d: date, m: int) -> date:
            yr = d.year + (d.month - 1 + m) // 12
            mo = (d.month - 1 + m) % 12 + 1
            dy = min(d.day, calendar.monthrange(yr, mo)[1])
            return date(yr, mo, dy)

        for r in rows:
            principal = r["principal"]
            rate = r["annual_rate"]
            months = r["term_months"]
            rollover_type = r["rollover_type"] or "withdraw"
            saving_type = r["saving_type"] or "fixed"
            start = date.fromisoformat(r["start_date"])
            maturity_date = add_months(start, months)
            actual_days = (maturity_date - start).days
            status = "matured" if maturity_date <= today else "active"
            days_remaining = (maturity_date - today).days if status == "active" else 0

            # Load withdrawals for flexible savings
            withdrawals: list[dict[str, Any]] = []
            if saving_type == "flexible":
                wrows = self.conn.execute(
                    "SELECT id, date, amount, note FROM saving_withdrawals WHERE saving_id = ? ORDER BY date ASC, created_at ASC",
                    (r["id"],),
                ).fetchall()
                withdrawals = [dict(w) for w in wrows]

            # Calculate interest
            if saving_type == "flexible" and withdrawals:
                # Segmented interest: each withdrawal creates a new segment
                segments: list[tuple[date, date, float]] = []
                seg_start = start
                running_principal = principal
                for w in withdrawals:
                    w_date = date.fromisoformat(w["date"])
                    if seg_start < w_date:
                        segments.append((seg_start, w_date, running_principal))
                    running_principal -= w["amount"]
                    seg_start = w_date
                # Final segment to maturity
                if seg_start < maturity_date:
                    segments.append((seg_start, maturity_date, running_principal))
                interest = sum(
                    p * (rate / 100.0) * (e - s).days / 365.0
                    for s, e, p in segments if p > 0
                )
                current_principal = principal - sum(w["amount"] for w in withdrawals)
            else:
                interest = principal * (rate / 100.0) * actual_days / 365.0
                current_principal = principal

            total = current_principal + interest

            # Projections (rollover) — use current_principal at maturity
            projections: list[dict[str, Any]] = []
            if rollover_type != "withdraw":
                proj_principal = current_principal
                max_terms = max(1, 60 // months)
                running_principal_p = proj_principal
                running_start = start
                cumulative_interest = 0.0
                for term_num in range(1, max_terms + 1):
                    t_maturity = add_months(running_start, months)
                    t_days = (t_maturity - running_start).days
                    t_interest = running_principal_p * (rate / 100.0) * t_days / 365.0
                    cumulative_interest += t_interest
                    if rollover_type == "rollover_full":
                        next_principal = running_principal_p + t_interest
                    else:
                        next_principal = running_principal_p
                    projections.append({
                        "term": term_num,
                        "start": running_start.isoformat(),
                        "maturity": t_maturity.isoformat(),
                        "principal": running_principal_p,
                        "interest": t_interest,
                        "cumulative_interest": cumulative_interest,
                        "total": running_principal_p + t_interest,
                        "value_at_end": (proj_principal + cumulative_interest) if rollover_type == "rollover_principal" else next_principal,
                    })
                    running_principal_p = next_principal
                    running_start = t_maturity

            results.append({
                "id": r["id"],
                "name": r["name"],
                "principal": principal,
                "current_principal": current_principal,
                "annual_rate": rate,
                "term_months": months,
                "start_date": r["start_date"],
                "maturity_date": maturity_date.isoformat(),
                "actual_days": actual_days,
                "interest": interest,
                "total": total,
                "status": status,
                "days_remaining": days_remaining,
                "rollover_type": rollover_type,
                "saving_type": saving_type,
                "projections": projections,
                "withdrawals": withdrawals,
                "note": r["note"],
                "fund_id": r["fund_id"],
                "fund_name": r["fund_name"],
            })
        results_active = sorted([s for s in results if s["status"] == "active"], key=lambda s: s["maturity_date"])
        results_matured = sorted([s for s in results if s["status"] == "matured"], key=lambda s: s["maturity_date"], reverse=True)
        return results_active + results_matured

    def add_saving(self, name: str, principal: float, annual_rate: float, term_months: int, start_date: str, rollover_type: str = "withdraw", note: str = "", fund_id: int | None = None, saving_type: str = "fixed") -> int:
        cursor = self.conn.execute(
            "INSERT INTO savings (name, principal, annual_rate, term_months, start_date, rollover_type, note, fund_id, saving_type) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (name.strip(), principal, annual_rate, term_months, start_date, rollover_type, note.strip(), fund_id, saving_type),
        )
        self.conn.commit()
        return cursor.lastrowid

    def update_saving(self, saving_id: int, name: str, principal: float, annual_rate: float, term_months: int, start_date: str, rollover_type: str = "withdraw", note: str = "", fund_id: int | None = None, saving_type: str = "fixed") -> bool:
        cursor = self.conn.execute(
            "UPDATE savings SET name=?, principal=?, annual_rate=?, term_months=?, start_date=?, rollover_type=?, note=?, fund_id=?, saving_type=? WHERE id=?",
            (name.strip(), principal, annual_rate, term_months, start_date, rollover_type, note.strip(), fund_id, saving_type, saving_id),
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def delete_saving(self, saving_id: int) -> bool:
        cursor = self.conn.execute("DELETE FROM savings WHERE id = ?", (saving_id,))
        self.conn.commit()
        return cursor.rowcount > 0

    def add_saving_withdrawal(self, saving_id: int, w_date: str, amount: float, note: str = "") -> int:
        cursor = self.conn.execute(
            "INSERT INTO saving_withdrawals (saving_id, date, amount, note) VALUES (?, ?, ?, ?)",
            (saving_id, w_date, amount, note.strip()),
        )
        self.conn.commit()
        return cursor.lastrowid

    def delete_saving_withdrawal(self, withdrawal_id: int) -> bool:
        cursor = self.conn.execute("DELETE FROM saving_withdrawals WHERE id = ?", (withdrawal_id,))
        self.conn.commit()
        return cursor.rowcount > 0

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

    def update_rule(self, rule_id: int, category: str | None = None, match_type: str | None = None, pattern: str | None = None, priority: int | None = None) -> bool:
        """Update fields of a rule. Returns True if updated."""
        fields = []
        params = []
        if category is not None:
            fields.append("category = ?")
            params.append(category.strip())
        if match_type is not None:
            fields.append("match_type = ?")
            params.append(match_type.strip())
        if pattern is not None:
            fields.append("pattern = ?")
            params.append(pattern.strip())
        if priority is not None:
            fields.append("priority = ?")
            params.append(priority)
        if not fields:
            return False
        params.append(rule_id)
        cursor = self.conn.execute(
            f"UPDATE category_rules SET {', '.join(fields)} WHERE id = ?",
            params,
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def delete_rule(self, rule_id: int) -> bool:
        """Delete a category rule. Returns True if deleted."""
        cursor = self.conn.execute("DELETE FROM category_rules WHERE id = ?", (rule_id,))
        self.conn.commit()
        return cursor.rowcount > 0

    def get_rule_stats(self) -> dict[int, int]:
        """Return a mapping of rule_id -> transaction count matched by that rule."""
        rules = self.get_rules()
        stats: dict[int, int] = {}
        for rule in rules:
            match_type = rule["match_type"]
            pattern = rule["pattern"]
            if match_type == "contains":
                param = f"%{pattern}%"
            elif match_type == "endswith":
                param = f"%{pattern}"
            else:
                stats[rule["id"]] = 0
                continue
            row = self.conn.execute(
                "SELECT COUNT(*) as cnt FROM transactions WHERE description LIKE ?",
                (param,),
            ).fetchone()
            stats[rule["id"]] = row["cnt"]
        return stats

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
