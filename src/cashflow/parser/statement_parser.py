"""Statement parser orchestrator — auto-detects credit card vs bank account statements."""

from __future__ import annotations

import logging
from pathlib import Path

import fitz  # PyMuPDF

from cashflow.models.transaction import ParseResult
from cashflow.parser.text_parser import _open_pdf

logger = logging.getLogger(__name__)

# Markers present in bank account (debit card) statements
_BANK_ACCOUNT_MARKERS = (
    "SỔ PHỤ KIÊM PHIẾU BÁO",
    "BANK STATEMENT/ DEBIT",
)


def _detect_statement_type(pdf_path: Path, password: str | None) -> str:
    """Peek at the first page to determine statement type.

    Returns 'bank_account' or 'credit_card'.
    """
    doc = _open_pdf(pdf_path, password)
    try:
        first_page_text = doc[0].get_text()
    finally:
        doc.close()

    for marker in _BANK_ACCOUNT_MARKERS:
        if marker in first_page_text:
            return "bank_account"
    return "credit_card"


def parse_statement(
    pdf_path: str | Path,
    password: str | None = None,
) -> ParseResult:
    """Parse a Techcombank statement, auto-detecting credit card vs bank account format.

    Args:
        pdf_path: Path to the PDF file.
        password: Password for encrypted PDFs.

    Returns:
        ParseResult with transactions and metadata.
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    stmt_type = _detect_statement_type(pdf_path, password)
    logger.info("Detected statement type '%s' for %s", stmt_type, pdf_path.name)

    if stmt_type == "bank_account":
        from cashflow.parser.bank_statement_parser import parse_bank_statement_pdf
        return parse_bank_statement_pdf(pdf_path, password=password)

    from cashflow.parser.text_parser import parse_text_pdf
    return parse_text_pdf(pdf_path, password=password)
