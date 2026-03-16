"""Pydantic models for Techcombank credit card statement data."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class TransactionType(str, Enum):
    DEBIT = "debit"
    CREDIT = "credit"


class Transaction(BaseModel):
    """A single credit card transaction."""

    transaction_date: date
    posting_date: Optional[date] = None
    description: str
    original_amount: Decimal
    original_currency: str = "VND"
    billing_amount_vnd: Decimal
    transaction_type: TransactionType = TransactionType.DEBIT
    category: Optional[str] = None
    merchant_name: Optional[str] = None
    card_last_four: Optional[str] = None
    reference_number: Optional[str] = None

    model_config = {"json_encoders": {Decimal: str, date: lambda v: v.strftime("%d/%m/%Y")}}


class StatementMetadata(BaseModel):
    """Metadata extracted from the statement header."""

    statement_date: Optional[date] = None
    due_date: Optional[date] = None
    min_payment: Optional[Decimal] = None
    total_due: Optional[Decimal] = None
    credit_limit: Optional[Decimal] = None
    card_number_masked: Optional[str] = None
    card_holder_name: Optional[str] = None
    statement_period_start: Optional[date] = None
    statement_period_end: Optional[date] = None
    source_file: Optional[str] = None


class ParseResult(BaseModel):
    """Result of parsing a PDF statement."""

    metadata: StatementMetadata = Field(default_factory=StatementMetadata)
    transactions: list[Transaction] = Field(default_factory=list)
    page_count: int = 0
    parse_method: str = "unknown"  # "text", "ocr", "hybrid"
    warnings: list[str] = Field(default_factory=list)

    @property
    def total_debit(self) -> Decimal:
        return sum(
            t.billing_amount_vnd
            for t in self.transactions
            if t.transaction_type == TransactionType.DEBIT
        )

    @property
    def total_credit(self) -> Decimal:
        return sum(
            t.billing_amount_vnd
            for t in self.transactions
            if t.transaction_type == TransactionType.CREDIT
        )

    @property
    def transaction_count(self) -> int:
        return len(self.transactions)
