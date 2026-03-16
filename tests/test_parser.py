"""Tests for Pydantic data models."""

from datetime import date
from decimal import Decimal

from techcombank_pdf.models.transaction import (
    ParseResult,
    StatementMetadata,
    Transaction,
    TransactionType,
)


class TestTransaction:
    def test_creation(self):
        txn = Transaction(
            transaction_date=date(2024, 1, 15),
            description="Test transaction",
            original_amount=Decimal("100000"),
            billing_amount_vnd=Decimal("100000"),
        )
        assert txn.transaction_type == TransactionType.DEBIT
        assert txn.original_currency == "VND"
        assert txn.posting_date is None

    def test_json_serialization(self):
        txn = Transaction(
            transaction_date=date(2024, 1, 15),
            description="Test",
            original_amount=Decimal("100000"),
            billing_amount_vnd=Decimal("100000"),
        )
        data = txn.model_dump(mode="json")
        # json_encoders formats dates as DD/MM/YYYY
        assert data["transaction_date"] == "15/01/2024"
        assert data["original_amount"] == "100000"

    def test_optional_fields(self):
        txn = Transaction(
            transaction_date=date(2024, 1, 15),
            description="Test",
            original_amount=Decimal("100"),
            billing_amount_vnd=Decimal("100"),
            category="Food",
            merchant_name="Grab",
            card_last_four="1234",
            reference_number="REF123",
        )
        assert txn.category == "Food"
        assert txn.merchant_name == "Grab"


class TestParseResult:
    def test_totals(self, sample_parse_result):
        assert sample_parse_result.total_debit == Decimal("185000")
        assert sample_parse_result.total_credit == Decimal("50000")

    def test_transaction_count(self, sample_parse_result):
        assert sample_parse_result.transaction_count == 3

    def test_empty(self):
        result = ParseResult()
        assert result.total_debit == Decimal("0")
        assert result.total_credit == Decimal("0")
        assert result.transaction_count == 0


class TestStatementMetadata:
    def test_defaults(self):
        meta = StatementMetadata()
        assert meta.statement_date is None
        assert meta.source_file is None

    def test_with_values(self):
        meta = StatementMetadata(
            statement_date=date(2024, 1, 31),
            card_number_masked="4XXX****1234",
            total_due=Decimal("500000"),
        )
        assert meta.statement_date == date(2024, 1, 31)
        assert meta.total_due == Decimal("500000")
