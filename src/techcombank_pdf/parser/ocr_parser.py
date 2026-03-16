"""OCR-based parser for scanned PDF statements using pytesseract."""

from __future__ import annotations

import logging
import re
from pathlib import Path

import pytesseract
from PIL import Image, ImageFilter

from techcombank_pdf.config import OCR_DPI, OCR_LANGUAGES
from techcombank_pdf.converter.pdf_to_image import convert_pdf_to_images
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

# Regex for a transaction line:
# DD/MM/YYYY  DD/MM/YYYY  <description>  <amount>
TRANSACTION_LINE_RE = re.compile(
    r"(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})\s+"  # transaction date
    r"(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})?\s*"  # posting date (optional)
    r"(.+?)\s+"  # description
    r"([\d.,]+(?:\s*(?:VND|VNĐ|USD|CR))?)\s*$"  # amount
)


def _preprocess_image(image_path: Path) -> Image.Image:
    """Pre-process image for better OCR accuracy."""
    img = Image.open(image_path)

    # Convert to grayscale
    if img.mode != "L":
        img = img.convert("L")

    # Sharpen
    img = img.filter(ImageFilter.SHARPEN)

    # Binarize (simple threshold)
    threshold = 160
    img = img.point(lambda p: 255 if p > threshold else 0, mode="1")

    return img


def _parse_ocr_text(text: str) -> list[Transaction]:
    """Parse OCR output text into transactions."""
    transactions: list[Transaction] = []

    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue

        match = TRANSACTION_LINE_RE.match(line)
        if not match:
            continue

        txn_date = parse_date(match.group(1))
        if not txn_date:
            continue

        posting_date = parse_date(match.group(2)) if match.group(2) else None
        description = normalize_vietnamese_text(match.group(3))
        amount_text = match.group(4)
        amount = parse_vnd_amount(amount_text)

        if amount is None:
            continue

        txn_type_str = detect_transaction_type(amount_text, description)
        txn_type = TransactionType(txn_type_str)

        transactions.append(
            Transaction(
                transaction_date=txn_date,
                posting_date=posting_date,
                description=description,
                original_amount=abs(amount),
                original_currency="VND",
                billing_amount_vnd=abs(amount),
                transaction_type=txn_type,
            )
        )

    return transactions


def parse_ocr_pdf(pdf_path: str | Path, password: str | None = None) -> ParseResult:
    """Parse a scanned PDF statement using OCR.

    Converts pages to images, preprocesses, and runs pytesseract.
    """
    pdf_path = Path(pdf_path)
    all_transactions: list[Transaction] = []
    warnings: list[str] = []

    # Convert PDF to images
    image_paths = convert_pdf_to_images(pdf_path, dpi=OCR_DPI, password=password)

    for page_num, image_path in enumerate(image_paths):
        try:
            processed_img = _preprocess_image(image_path)
            text = pytesseract.image_to_string(
                processed_img,
                lang=OCR_LANGUAGES,
                config="--psm 6",  # Assume uniform block of text
            )
            page_transactions = _parse_ocr_text(text)
            all_transactions.extend(page_transactions)

            if not page_transactions:
                logger.debug("No transactions found on page %d via OCR", page_num + 1)

        except Exception as e:
            warnings.append(f"OCR failed on page {page_num + 1}: {e}")

    return ParseResult(
        metadata=StatementMetadata(source_file=pdf_path.name),
        transactions=all_transactions,
        page_count=len(image_paths),
        parse_method="ocr",
        warnings=warnings,
    )
