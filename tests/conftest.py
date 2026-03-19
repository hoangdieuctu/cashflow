"""Shared test fixtures."""

import json
import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from cashflow.models.transaction import (
    ParseResult,
    StatementMetadata,
    Transaction,
    TransactionType,
)


@pytest.fixture
def sample_transactions() -> list[Transaction]:
    """Sample transactions for testing."""
    return [
        Transaction(
            transaction_date=date(2024, 1, 15),
            posting_date=date(2024, 1, 16),
            description="GRAB*GRABFOOD HO CHI MINH",
            original_amount=Decimal("150000"),
            original_currency="VND",
            billing_amount_vnd=Decimal("150000"),
            transaction_type=TransactionType.DEBIT,
            category="Food & Drink",
            merchant_name="Grab",
        ),
        Transaction(
            transaction_date=date(2024, 1, 18),
            posting_date=date(2024, 1, 19),
            description="Thanh toán trực tuyến - Hoàn tiền",
            original_amount=Decimal("50000"),
            original_currency="VND",
            billing_amount_vnd=Decimal("50000"),
            transaction_type=TransactionType.CREDIT,
        ),
        Transaction(
            transaction_date=date(2024, 2, 1),
            description="CIRCLE K VN C/S 12345",
            original_amount=Decimal("35000"),
            original_currency="VND",
            billing_amount_vnd=Decimal("35000"),
            transaction_type=TransactionType.DEBIT,
        ),
    ]


@pytest.fixture
def sample_parse_result(sample_transactions) -> ParseResult:
    """Sample ParseResult for testing."""
    return ParseResult(
        metadata=StatementMetadata(
            statement_date=date(2024, 1, 31),
            due_date=date(2024, 2, 25),
            card_number_masked="4XXX****XXXX1234",
            source_file="test_statement.pdf",
            total_due=Decimal("135000"),
        ),
        transactions=sample_transactions,
        page_count=2,
        parse_method="text",
    )


@pytest.fixture
def tmp_dir():
    """Temporary directory for test outputs."""
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def tmp_db(tmp_dir):
    """Temporary database path."""
    return str(tmp_dir / "test.db")
