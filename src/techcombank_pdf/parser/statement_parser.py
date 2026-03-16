"""Statement parser orchestrator."""

from __future__ import annotations

import logging
from pathlib import Path

from techcombank_pdf.models.transaction import ParseResult
from techcombank_pdf.parser.text_parser import parse_text_pdf

logger = logging.getLogger(__name__)


def parse_statement(
    pdf_path: str | Path,
    password: str | None = None,
) -> ParseResult:
    """Parse a Techcombank credit card statement.

    Args:
        pdf_path: Path to the PDF file.
        password: Password for encrypted PDFs.

    Returns:
        ParseResult with transactions and metadata.
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    logger.info("Parsing %s", pdf_path.name)
    return parse_text_pdf(pdf_path, password=password)
