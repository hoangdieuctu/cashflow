"""Extract transactions from text-based PDFs using pdfplumber."""

from __future__ import annotations

import logging
import re
from decimal import Decimal
from pathlib import Path

import pdfplumber

from techcombank_pdf.config import STATEMENT_HEADER_PATTERNS, TABLE_HEADER_PATTERNS
from techcombank_pdf.models.transaction import (
    ParseResult,
    StatementMetadata,
    Transaction,
    TransactionType,
)
from techcombank_pdf.parser.normalizer import (
    detect_transaction_type,
    normalize_vietnamese_text,
    parse_date,
    parse_vnd_amount,
)

logger = logging.getLogger(__name__)


def _is_statement_page(text: str) -> bool:
    """Check if page text contains Techcombank statement markers."""
    text_upper = text.upper()
    return any(p.upper() in text_upper for p in STATEMENT_HEADER_PATTERNS)


def _find_table_columns(table_header_row: list[str]) -> dict[str, int]:
    """Map column names to indices based on header patterns."""
    col_map: dict[str, int] = {}
    for idx, cell in enumerate(table_header_row):
        if not cell:
            continue
        cell_norm = cell.strip().upper()
        for col_name, patterns in TABLE_HEADER_PATTERNS.items():
            if any(p.upper() in cell_norm for p in patterns):
                col_map[col_name] = idx
                break
    return col_map


def _extract_metadata_from_text(full_text: str) -> StatementMetadata:
    """Extract statement metadata from the raw text of the PDF."""
    meta = StatementMetadata()

    # Card number (masked)
    card_match = re.search(r"(\d{4}\s*[*Xx]{4,8}\s*\d{4})", full_text)
    if card_match:
        meta.card_number_masked = card_match.group(1).replace(" ", "")

    # Statement date patterns
    date_patterns = [
        (r"[Nn]gày\s+sao\s+kê[:\s]*(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})", "statement_date"),
        (r"[Ss]tatement\s+[Dd]ate[:\s]*(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})", "statement_date"),
        (r"[Nn]gày\s+đến\s+hạn[:\s]*(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})", "due_date"),
        (r"[Dd]ue\s+[Dd]ate[:\s]*(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})", "due_date"),
    ]
    for pattern, field in date_patterns:
        match = re.search(pattern, full_text)
        if match:
            parsed = parse_date(match.group(1))
            if parsed:
                setattr(meta, field, parsed)

    # Amounts
    amount_patterns = [
        (r"[Tt]ổng\s+(?:số\s+)?dư\s+nợ[:\s]*([\d.,]+)", "total_due"),
        (r"[Tt]otal\s+[Dd]ue[:\s]*([\d.,]+)", "total_due"),
        (r"[Tt]hanh\s+toán\s+tối\s+thiểu[:\s]*([\d.,]+)", "min_payment"),
        (r"[Mm]in(?:imum)?\s+[Pp]ayment[:\s]*([\d.,]+)", "min_payment"),
        (r"[Hh]ạn\s+mức[:\s]*([\d.,]+)", "credit_limit"),
        (r"[Cc]redit\s+[Ll]imit[:\s]*([\d.,]+)", "credit_limit"),
    ]
    for pattern, field in amount_patterns:
        match = re.search(pattern, full_text)
        if match:
            parsed = parse_vnd_amount(match.group(1))
            if parsed:
                setattr(meta, field, parsed)

    return meta


def parse_text_pdf(pdf_path: str | Path) -> ParseResult:
    """Parse a text-based Techcombank PDF statement using pdfplumber.

    Returns a ParseResult with extracted transactions and metadata.
    """
    pdf_path = Path(pdf_path)
    transactions: list[Transaction] = []
    warnings: list[str] = []
    full_text_parts: list[str] = []

    with pdfplumber.open(str(pdf_path)) as pdf:
        page_count = len(pdf.pages)

        for page_num, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            full_text_parts.append(text)

            tables = page.extract_tables()
            if not tables:
                logger.debug("No tables found on page %d", page_num + 1)
                continue

            for table in tables:
                if not table or len(table) < 2:
                    continue

                # Try to identify columns from header row
                col_map = _find_table_columns(table[0])
                if not col_map:
                    # Try second row in case first is a title row
                    if len(table) > 2:
                        col_map = _find_table_columns(table[1])
                        data_rows = table[2:]
                    else:
                        continue
                else:
                    data_rows = table[1:]

                for row in data_rows:
                    try:
                        txn = _parse_row(row, col_map)
                        if txn:
                            transactions.append(txn)
                    except Exception as e:
                        warnings.append(f"Page {page_num + 1}: Failed to parse row: {e}")

        full_text = "\n".join(full_text_parts)
        metadata = _extract_metadata_from_text(full_text)
        metadata.source_file = str(pdf_path.name)

    return ParseResult(
        metadata=metadata,
        transactions=transactions,
        page_count=page_count,
        parse_method="text",
        warnings=warnings,
    )


def _parse_row(row: list[str | None], col_map: dict[str, int]) -> Transaction | None:
    """Parse a single table row into a Transaction."""
    # Get date — required field
    date_idx = col_map.get("transaction_date")
    if date_idx is None or date_idx >= len(row) or not row[date_idx]:
        return None

    txn_date = parse_date(row[date_idx])
    if not txn_date:
        return None

    # Posting date
    posting_date = None
    post_idx = col_map.get("posting_date")
    if post_idx is not None and post_idx < len(row) and row[post_idx]:
        posting_date = parse_date(row[post_idx])

    # Description
    desc_idx = col_map.get("description")
    description = ""
    if desc_idx is not None and desc_idx < len(row) and row[desc_idx]:
        description = normalize_vietnamese_text(row[desc_idx])

    # Amount
    amt_idx = col_map.get("amount")
    if amt_idx is None or amt_idx >= len(row) or not row[amt_idx]:
        return None

    amount_text = row[amt_idx]
    amount = parse_vnd_amount(amount_text)
    if amount is None:
        return None

    # Currency
    currency = "VND"
    curr_idx = col_map.get("currency")
    if curr_idx is not None and curr_idx < len(row) and row[curr_idx]:
        currency = row[curr_idx].strip().upper()

    # Transaction type
    txn_type_str = detect_transaction_type(amount_text, description)
    txn_type = TransactionType(txn_type_str)
    billing_amount = abs(amount)

    return Transaction(
        transaction_date=txn_date,
        posting_date=posting_date,
        description=description,
        original_amount=abs(amount),
        original_currency=currency,
        billing_amount_vnd=billing_amount,
        transaction_type=txn_type,
    )
