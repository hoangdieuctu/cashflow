"""Statement parser orchestrator — text-first with OCR fallback."""

from __future__ import annotations

import logging
from pathlib import Path

from techcombank_pdf.models.transaction import ParseResult
from techcombank_pdf.parser.ocr_parser import parse_ocr_pdf
from techcombank_pdf.parser.text_parser import parse_text_pdf

logger = logging.getLogger(__name__)


def parse_statement(
    pdf_path: str | Path,
    force_ocr: bool = False,
    min_transactions: int = 1,
) -> ParseResult:
    """Parse a Techcombank credit card statement.

    Strategy:
    1. Try text extraction first (faster, more accurate for digital PDFs).
    2. If text extraction yields fewer than min_transactions, fall back to OCR.
    3. If force_ocr is True, skip text extraction entirely.

    Args:
        pdf_path: Path to the PDF file.
        force_ocr: Skip text extraction and use OCR directly.
        min_transactions: Minimum transactions expected from text extraction
                         before falling back to OCR.

    Returns:
        ParseResult with transactions and metadata.
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    if force_ocr:
        logger.info("Forced OCR mode for %s", pdf_path.name)
        return parse_ocr_pdf(pdf_path)

    # Try text extraction first
    logger.info("Attempting text extraction for %s", pdf_path.name)
    result = parse_text_pdf(pdf_path)

    if result.transaction_count >= min_transactions:
        logger.info(
            "Text extraction found %d transactions", result.transaction_count
        )
        return result

    # Fall back to OCR
    logger.info(
        "Text extraction found only %d transactions, falling back to OCR",
        result.transaction_count,
    )
    ocr_result = parse_ocr_pdf(pdf_path)

    if ocr_result.transaction_count > result.transaction_count:
        ocr_result.parse_method = "ocr"
        ocr_result.warnings.insert(
            0, "Text extraction yielded insufficient results; used OCR fallback."
        )
        # Merge metadata from text extraction (usually better)
        if result.metadata.statement_date:
            ocr_result.metadata = result.metadata
        return ocr_result

    # Text extraction was better (or equally empty)
    result.parse_method = "hybrid" if ocr_result.transactions else "text"
    return result
