"""Tests for the database layer."""

from datetime import date
from decimal import Decimal

import pytest

from techcombank_pdf.database.db import init_db
from techcombank_pdf.database.repository import Repository
from techcombank_pdf.models.transaction import (
    ParseResult,
    StatementMetadata,
    Transaction,
    TransactionType,
)


class TestDatabase:
    def test_init_creates_tables(self, tmp_db):
        conn = init_db(tmp_db)
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = {row["name"] for row in tables}
        assert "statements" in table_names
        assert "transactions" in table_names
        conn.close()


class TestRepository:
    def test_import_and_query(self, sample_parse_result, tmp_db):
        with Repository(tmp_db) as repo:
            stmt_id = repo.import_parse_result(sample_parse_result)
            assert stmt_id is not None

            txns = repo.get_transactions()
            assert len(txns) == 3

    def test_query_with_filters(self, sample_parse_result, tmp_db):
        with Repository(tmp_db) as repo:
            repo.import_parse_result(sample_parse_result)

            # Filter by type
            debits = repo.get_transactions(transaction_type="debit")
            assert len(debits) == 2

            credits = repo.get_transactions(transaction_type="credit")
            assert len(credits) == 1

    def test_query_with_search(self, sample_parse_result, tmp_db):
        with Repository(tmp_db) as repo:
            repo.import_parse_result(sample_parse_result)

            results = repo.get_transactions(search="GRAB")
            assert len(results) == 1
            assert "GRAB" in results[0]["description"]

    def test_spending_summary(self, sample_parse_result, tmp_db):
        with Repository(tmp_db) as repo:
            repo.import_parse_result(sample_parse_result)
            summary = repo.get_spending_summary()

            assert summary["total_transactions"] == 3
            assert summary["total_debit"] == 185000.0
            assert summary["total_credit"] == 50000.0

    def test_get_statements(self, sample_parse_result, tmp_db):
        with Repository(tmp_db) as repo:
            repo.import_parse_result(sample_parse_result)
            stmts = repo.get_statements()
            assert len(stmts) == 1
            assert stmts[0]["transaction_count"] == 3

    def test_reimport_idempotent(self, sample_parse_result, tmp_db):
        with Repository(tmp_db) as repo:
            repo.import_parse_result(sample_parse_result)
            repo.import_parse_result(sample_parse_result)

            # Should not duplicate
            stmts = repo.get_statements()
            assert len(stmts) == 1

    def test_transaction_count(self, sample_parse_result, tmp_db):
        with Repository(tmp_db) as repo:
            repo.import_parse_result(sample_parse_result)
            assert repo.get_transaction_count() == 3

    def test_date_filter(self, sample_parse_result, tmp_db):
        with Repository(tmp_db) as repo:
            repo.import_parse_result(sample_parse_result)

            txns = repo.get_transactions(start_date="2024-01-18")
            assert len(txns) == 2  # Jan 18 + Feb 1

            txns = repo.get_transactions(end_date="2024-01-17")
            assert len(txns) == 1  # Only Jan 15
