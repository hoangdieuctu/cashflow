"""Extract transactions from Techcombank PDF statements.

Uses PyMuPDF for text extraction since Techcombank statements use
line-based layouts rather than PDF table structures.
"""

from __future__ import annotations

import logging
import re
from decimal import Decimal
from pathlib import Path

import fitz  # PyMuPDF

from techcombank_pdf.models.transaction import (
    ParseResult,
    StatementMetadata,
    Transaction,
    TransactionType,
)
from techcombank_pdf.parser.normalizer import (
    normalize_vietnamese_text,
    parse_date,
    parse_vnd_amount,
)

logger = logging.getLogger(__name__)

# Regex patterns
DATE_RE = re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$")
AMOUNT_VND_RE = re.compile(r"^[\d,]+ VND$")
AMOUNT_PLAIN_RE = re.compile(r"^[\d,]+$")
PAGE_NUMBER_RE = re.compile(r"^\d+ / \d+$")
CARD_NO_RE = re.compile(r"Số Thẻ/Card No:\s*(\d{4})\.\.\.([\d]+)")


def _open_pdf(pdf_path: Path, password: str | None) -> fitz.Document:
    """Open a PDF with optional password, raising clear errors."""
    doc = fitz.open(str(pdf_path))
    if doc.is_encrypted:
        if not password:
            doc.close()
            raise ValueError(
                "PDF is password-protected. Please provide the correct password."
            )
        if not doc.authenticate(password):
            doc.close()
            raise ValueError("Invalid PDF password.")
    return doc


def _extract_metadata_from_text(full_text: str) -> StatementMetadata:
    """Extract statement metadata from the raw text of the PDF."""
    meta = StatementMetadata()

    # Card account number
    acct_match = re.search(r"Credit Card Account Number\n(\d+)", full_text)
    if acct_match:
        meta.card_number_masked = acct_match.group(1)

    # Card last four from transaction lines
    card_match = CARD_NO_RE.search(full_text)
    if card_match:
        meta.card_holder_name = None  # populated separately

    # Cardholder name
    name_match = re.search(r"Mr/Ms\n(.+)", full_text)
    if name_match:
        meta.card_holder_name = name_match.group(1).strip()

    # Statement date
    stmt_match = re.search(r"Statement Date\n(\d{1,2}/\d{1,2}/\d{4})", full_text)
    if stmt_match:
        meta.statement_date = parse_date(stmt_match.group(1))

    # Due date
    due_match = re.search(r"Payment due date\n.*?\n(\d{1,2}/\d{1,2}/\d{4})", full_text, re.DOTALL)
    if due_match:
        meta.due_date = parse_date(due_match.group(1))

    # Statement balance (total due)
    balance_match = re.search(r"Statement Balance\n-?([\d,]+)", full_text)
    if balance_match:
        meta.total_due = parse_vnd_amount(balance_match.group(1))

    # Minimum payment
    min_match = re.search(r"Minimum Payment Due\n([\d,]+)", full_text)
    if min_match:
        meta.min_payment = parse_vnd_amount(min_match.group(1))

    # Credit limit
    limit_match = re.search(r"Credit Limit\n([\d,]+)", full_text)
    if limit_match:
        meta.credit_limit = parse_vnd_amount(limit_match.group(1))

    return meta


def _parse_transactions_from_lines(lines: list[str]) -> tuple[list[Transaction], list[str]]:
    """Parse transactions from extracted text lines.

    Techcombank statement format (per transaction):
        DD/MM/YYYY              ← transaction date
        DD/MM/YYYY              ← posting date
        NNN,NNN VND             ← original amount
        NNN,NNN                 ← debit/credit amount (or amount + description for credits)
        Description line 1      ← transaction description
        Merchant/location       ← merchant name

    Credit (payment) transactions have the amount on the credit column
    with inline description text.
    """
    transactions: list[Transaction] = []
    warnings: list[str] = []
    i = 0

    while i < len(lines):
        line = lines[i].strip()

        # Look for transaction date as entry point
        if not DATE_RE.match(line):
            i += 1
            continue

        txn_date = parse_date(line)
        if not txn_date:
            i += 1
            continue

        # Need at least a few more lines for a transaction
        if i + 3 >= len(lines):
            break

        # Next line should be posting date
        next_line = lines[i + 1].strip()
        if not DATE_RE.match(next_line):
            i += 1
            continue

        posting_date = parse_date(next_line)

        # Next line should be amount with VND
        amount_line = lines[i + 2].strip()
        if not AMOUNT_VND_RE.match(amount_line):
            i += 1
            continue

        original_amount = parse_vnd_amount(amount_line)
        if original_amount is None:
            i += 1
            continue

        # Next line: debit amount (plain number) or credit amount with description
        debit_credit_line = lines[i + 3].strip()

        transaction_type = TransactionType.DEBIT
        billing_amount = original_amount
        description_parts: list[str] = []
        card_last_four: str | None = None

        if AMOUNT_PLAIN_RE.match(debit_credit_line):
            # Normal debit: plain amount, then description lines follow
            billing_amount = parse_vnd_amount(debit_credit_line) or original_amount
            j = i + 4

            # Collect description lines until next date or end
            while j < len(lines):
                desc_line = lines[j].strip()
                if DATE_RE.match(desc_line) or PAGE_NUMBER_RE.match(desc_line):
                    break
                if desc_line.startswith("Tổng ghi") or desc_line.startswith("Số dư cần"):
                    break
                if desc_line:
                    description_parts.append(desc_line)
                j += 1

            i = j
        else:
            # Credit transaction: amount + description on same line
            # e.g. "58,267,356 Thanh toan no the tin dung..."
            credit_match = re.match(r"([\d,]+)\s+(.+)", debit_credit_line)
            if credit_match:
                billing_amount = parse_vnd_amount(credit_match.group(1)) or original_amount
                description_parts.append(credit_match.group(2))
                transaction_type = TransactionType.CREDIT
                j = i + 4
                # Collect remaining description lines
                while j < len(lines):
                    desc_line = lines[j].strip()
                    if DATE_RE.match(desc_line) or PAGE_NUMBER_RE.match(desc_line):
                        break
                    if desc_line.startswith("Tổng ghi") or desc_line.startswith("Số dư cần"):
                        break
                    if desc_line:
                        description_parts.append(desc_line)
                    j += 1
                i = j
            else:
                i += 1
                continue

        # Extract card last four from description
        full_desc = " ".join(description_parts)
        card_match = CARD_NO_RE.search(full_desc)
        if card_match:
            card_last_four = card_match.group(2)

        # Clean up description — remove the "Giao dịch thanh toán/Purchase" prefix
        # and card number info, keep just the merchant name
        merchant_name = None
        if len(description_parts) >= 2:
            merchant_name = normalize_vietnamese_text(description_parts[-1])
        desc_clean = normalize_vietnamese_text(full_desc)

        transactions.append(
            Transaction(
                transaction_date=txn_date,
                posting_date=posting_date,
                description=desc_clean,
                original_amount=abs(billing_amount),
                original_currency="VND",
                billing_amount_vnd=abs(billing_amount),
                transaction_type=transaction_type,
                card_last_four=card_last_four,
                merchant_name=merchant_name,
            )
        )

    return transactions, warnings


def parse_text_pdf(pdf_path: str | Path, password: str | None = None) -> ParseResult:
    """Parse a Techcombank PDF statement by extracting text line-by-line.

    Uses PyMuPDF for text extraction since Techcombank statements use
    line-based layouts rather than PDF table structures.
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    doc = _open_pdf(pdf_path, password)

    try:
        all_lines: list[str] = []
        full_text_parts: list[str] = []
        page_count = doc.page_count

        for page_num in range(page_count):
            page = doc[page_num]
            text = page.get_text()
            full_text_parts.append(text)

            for line in text.split("\n"):
                stripped = line.strip()
                if stripped:
                    all_lines.append(stripped)

        full_text = "\n".join(full_text_parts)
        metadata = _extract_metadata_from_text(full_text)
        metadata.source_file = str(pdf_path.name)

        transactions, warnings = _parse_transactions_from_lines(all_lines)

        logger.info("Extracted %d transactions from %s", len(transactions), pdf_path.name)

    finally:
        doc.close()

    return ParseResult(
        metadata=metadata,
        transactions=transactions,
        page_count=page_count,
        parse_method="text",
        warnings=warnings,
    )
