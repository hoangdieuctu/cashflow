"""Parse Techcombank bank account (debit card) statements.

Uses PyMuPDF spatial word extraction to distinguish the Debit column
(Nợ TKTT) from the Credit column (Có TKTT) by Y-coordinate, since
plain-text extraction only emits one amount per transaction and cannot
differentiate which column it came from.

Column Y-coordinates (consistent across all pages in landscape PDFs):
  y ≈ 217  →  Debit  (money out)
  y ≈ 123  →  Credit (money in)
  y ≈ 19   →  Balance (running balance)
"""

from __future__ import annotations

import logging
import re
from decimal import Decimal
from pathlib import Path

import fitz  # PyMuPDF

from cashflow.models.transaction import (
    ParseResult,
    StatementMetadata,
    StatementType,
    Transaction,
    TransactionType,
)
from cashflow.parser.normalizer import parse_date, parse_vnd_amount
from cashflow.parser.text_parser import _open_pdf

logger = logging.getLogger(__name__)

# Y-coordinate thresholds for column detection (±20 tolerance)
_Y_DEBIT_CENTER = 217
_Y_CREDIT_CENTER = 123
_Y_BALANCE_CENTER = 19
_Y_TOLERANCE = 20

# Patterns
DATE_RE = re.compile(r"^(?:0?[1-9]|[12]\d|3[01])/(?:0?[1-9]|1[0-2])/\d{4}$")
DATE_TIME_RE = re.compile(r"^\d{1,2}/\d{1,2}/\d{4}\s+\d{2}:\d{2}:\d{2}$")
REF_RE = re.compile(r"^FT[A-Z0-9\\]+$", re.IGNORECASE)
PAGE_NO_RE = re.compile(r"^\d+/\d+$")
AMOUNT_RE = re.compile(r"^[\d,]+$")
# VND amount: comma-grouped (e.g. 10,800,000) or small plain number (≤9 digits, e.g. 826).
# Excludes long reference-number strings like 14604150494929.
AMOUNT_VND_RE = re.compile(r"^(?:\d{1,3}(?:,\d{3})+|\d{1,9})$")


def _col(y: float) -> str | None:
    """Map a Y coordinate to a column name."""
    if abs(y - _Y_DEBIT_CENTER) <= _Y_TOLERANCE:
        return "debit"
    if abs(y - _Y_CREDIT_CENTER) <= _Y_TOLERANCE:
        return "credit"
    if abs(y - _Y_BALANCE_CENTER) <= _Y_TOLERANCE:
        return "balance"
    return None


def _is_noise(line: str) -> bool:
    """Return True for footer/header lines that should be skipped."""
    return (
        "Phiếu này được in" in line
        or "This document was generated" in line
        or DATE_TIME_RE.match(line) is not None
        or PAGE_NO_RE.match(line) is not None
        or line.startswith("Ngày giao dịch")
        or line.startswith("Transaction Date")
        or line in {
            "Đối tác", "Remitter", "NH Đối tác", "Remitter Bank",
            "Diễn giải", "Details", "Số bút toán", "Transaction No",
            "Nợ TKTT", "Debit", "Có TKTT", "Credit", "Số dư (2)", "Balance",
        }
    )


def _extract_metadata(full_text: str) -> StatementMetadata:
    meta = StatementMetadata(statement_type=StatementType.BANK_ACCOUNT)

    # Period dates: 'Từ ngày/ From:\n Đến ngày/ To:\nDD/MM/YYYY\nDD/MM/YYYY'
    period_match = re.search(
        r"Từ ngày/ From:\s*\n\s*Đến ngày/ To:\s*\n(\d{1,2}/\d{1,2}/\d{4})\s*\n(\d{1,2}/\d{1,2}/\d{4})",
        full_text,
    )
    if period_match:
        meta.statement_period_start = parse_date(period_match.group(1))
        meta.statement_period_end = parse_date(period_match.group(2))
        meta.statement_date = meta.statement_period_end

    # Customer name: three labels together, then three values
    name_match = re.search(
        r"Customer name:\nSố ID khách hàng/ Customer ID:\nĐịa chỉ/ Address:\n([A-Z][A-Z ]+)",
        full_text,
    )
    if name_match:
        meta.card_holder_name = name_match.group(1).strip()

    # Account number: after VND currency line
    acct_match = re.search(
        r"Account no\.:\nLoại tài khoản/ Type of account:\nTên tài khoản/ Account name:\nVND\n(\d+)",
        full_text,
    )
    if acct_match:
        meta.account_number = acct_match.group(1).strip()

    # Opening balance
    open_match = re.search(r"Số dư đầu kỳ/ Opening balance\n([\d,]+)", full_text)
    if open_match:
        meta.opening_balance = parse_vnd_amount(open_match.group(1))

    # Ending balance
    end_match = re.search(r"Số dư cuối kỳ/ Ending balance\n([\d,]+)", full_text)
    if end_match:
        meta.ending_balance = parse_vnd_amount(end_match.group(1))

    return meta


def _extract_spatial_amounts(doc: fitz.Document) -> dict[int, dict[str, Decimal]]:
    """Extract per-transaction-row amounts by spatial Y-column detection.

    Returns a dict keyed by the transaction's X index (row index within the
    page) mapping to {'debit': ..., 'credit': ..., 'balance': ...}.
    We use a global sequential row key: (page_num, row_x_rounded).
    """
    amounts: dict[tuple[int, int], dict[str, Decimal]] = {}

    for page_num in range(doc.page_count):
        page = doc[page_num]
        words = page.get_text("words")  # (x0,y0,x1,y1,word,bn,ln,wn)
        for x0, y0, x1, y1, word, *_ in words:
            if not AMOUNT_RE.match(word):
                continue
            col = _col(y0)
            if col is None:
                continue
            key = (page_num, round(x0 / 5) * 5)
            if key not in amounts:
                amounts[key] = {}
            amounts[key][col] = parse_vnd_amount(word) or Decimal(0)

    return amounts


def _parse_transactions(
    all_lines: list[str],
    amounts: dict[tuple[int, int], dict[str, Decimal]],
    doc: fitz.Document,
) -> tuple[list[Transaction], list[str]]:
    """Parse transactions from text lines using spatial amounts for debit/credit.

    Block boundary rule: a new transaction starts immediately after the balance
    line. Every transaction ends with two consecutive VND amount lines:
    the debit/credit amount then the running balance. The next line after the
    balance line is the first line of the next transaction.
    """
    transactions: list[Transaction] = []
    warnings: list[str] = []

    # Build ordered list of amount rows per page (rows that have debit or credit + balance)
    page_rows: dict[int, list[tuple[int, dict[str, Decimal]]]] = {}
    for (pg, x_key), cols in sorted(amounts.items()):
        if ("debit" in cols or "credit" in cols) and "balance" in cols:
            page_rows.setdefault(pg, []).append((x_key, cols))

    # --- Split text into transaction blocks ---
    # Strategy: split after each balance line (two consecutive VND amount lines).
    # Skip everything before the opening balance sentinel.
    STOP_PREFIXES = (
        "Cộng doanh số",
        "Số dư cuối kỳ",
        "Diễn giải/",
    )

    txn_blocks: list[list[str]] = []
    current: list[str] = []
    past_opening_balance = False
    past_opening_value = False  # skip the opening balance number itself
    prev_was_amount = False
    split_next = False  # split before the next non-noise line
    done = False  # stop collecting after footer sentinel

    for line in all_lines:
        if _is_noise(line):
            continue

        if not past_opening_balance:
            if line.startswith("Số dư đầu kỳ"):
                past_opening_balance = True
            prev_was_amount = False
            continue

        # Skip the opening balance number line (e.g. "39,075,579")
        if not past_opening_value:
            if AMOUNT_VND_RE.match(line):
                past_opening_value = True
            prev_was_amount = False
            continue

        if done:
            continue

        if any(line.startswith(p) for p in STOP_PREFIXES):
            if current:
                txn_blocks.append(current)
                current = []
            prev_was_amount = False
            split_next = False
            done = True
            continue

        is_amount = bool(AMOUNT_VND_RE.match(line))

        if split_next:
            if current:
                txn_blocks.append(current)
                current = []
            split_next = False

        current.append(line)

        # Two consecutive amount lines = debit/credit then balance → split after this line
        if is_amount and prev_was_amount:
            split_next = True

        prev_was_amount = is_amount

    if current:
        txn_blocks.append(current)

    # Flatten page_rows into a single ordered list
    ordered_rows: list[tuple[int, dict[str, Decimal]]] = []
    for pg in sorted(page_rows.keys()):
        ordered_rows.extend(page_rows[pg])

    if len(txn_blocks) != len(ordered_rows):
        warnings.append(
            f"Row count mismatch: {len(txn_blocks)} text blocks vs "
            f"{len(ordered_rows)} spatial rows — some transactions may be wrong"
        )
        logger.debug("--- text blocks (%d) ---", len(txn_blocks))
        for i, blk in enumerate(txn_blocks):
            logger.debug("  text[%d]: %s", i, blk[:3])
        logger.debug("--- spatial rows (%d) ---", len(ordered_rows))
        for i, (x_key, cols) in enumerate(ordered_rows):
            logger.debug("  spatial[%d]: x_key=%s cols=%s", i, x_key, cols)

    for idx, block in enumerate(txn_blocks):
        if not block:
            continue

        txn_date = parse_date(block[0])
        if not txn_date:
            warnings.append(f"Could not parse date from block: {block[0]!r}")
            continue

        # Find the reference number (starts with FT)
        ref_no: str | None = None
        ref_idx: int | None = None
        for j, line in enumerate(block):
            if REF_RE.match(line):
                ref_no = line
                ref_idx = j
                break

        # Description: everything between date and ref (or end of block), excluding amounts
        end = ref_idx if ref_idx is not None else len(block)
        desc_lines = [
            l for l in block[1:end]
            if l and not _is_noise(l) and not AMOUNT_VND_RE.match(l)
        ]

        description = " ".join(desc_lines)
        merchant_name = desc_lines[-1] if desc_lines else None

        # Get amounts from spatial data
        if idx < len(ordered_rows):
            _, cols = ordered_rows[idx]
            if "debit" in cols:
                txn_type = TransactionType.DEBIT
                amount = cols["debit"]
            else:
                txn_type = TransactionType.CREDIT
                amount = cols.get("credit", Decimal(0))
            balance = cols.get("balance", None)
        else:
            txn_type = TransactionType.DEBIT
            amount = Decimal(0)
            balance = None
            warnings.append(f"No spatial amount for transaction {idx}: {block[0]!r}")

        transactions.append(
            Transaction(
                transaction_date=txn_date,
                description=description or "(no description)",
                original_amount=amount,
                original_currency="VND",
                billing_amount_vnd=amount,
                transaction_type=txn_type,
                merchant_name=merchant_name,
                reference_number=ref_no,
                running_balance=balance,
            )
        )

    return transactions, warnings


def parse_bank_statement_pdf(
    pdf_path: str | Path, password: str | None = None
) -> ParseResult:
    """Parse a Techcombank bank account statement (debit card / SỔ PHỤ)."""
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
        metadata = _extract_metadata(full_text)
        metadata.source_file = str(pdf_path.name)

        amounts = _extract_spatial_amounts(doc)
        transactions, warnings = _parse_transactions(
            all_lines, amounts, doc,
        )

        logger.info(
            "Extracted %d transactions from bank statement %s",
            len(transactions),
            pdf_path.name,
        )

    finally:
        doc.close()

    return ParseResult(
        metadata=metadata,
        transactions=transactions,
        page_count=page_count,
        parse_method="text+spatial",
        warnings=warnings,
    )
