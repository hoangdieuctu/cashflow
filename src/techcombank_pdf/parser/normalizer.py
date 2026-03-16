"""Normalize Techcombank statement data — amounts, dates, Vietnamese text."""

from __future__ import annotations

import re
import unicodedata
from datetime import date
from decimal import Decimal, InvalidOperation


def parse_vnd_amount(text: str) -> Decimal | None:
    """Parse a VND amount string.

    Techcombank uses dot as thousands separator, comma as decimal separator.
    Examples: "1.234.567" → 1234567, "1.234.567,89" → 1234567.89
    Also handles plain numbers like "1234567".
    """
    if not text:
        return None

    cleaned = text.strip()
    # Remove currency labels
    cleaned = re.sub(r"(VND|VNĐ|USD|EUR)\s*", "", cleaned, flags=re.IGNORECASE)
    # Remove whitespace
    cleaned = cleaned.replace(" ", "")
    # Handle negative amounts in parentheses: (1.234.567) → -1234567
    negative = False
    if cleaned.startswith("(") and cleaned.endswith(")"):
        negative = True
        cleaned = cleaned[1:-1]
    elif cleaned.startswith("-"):
        negative = True
        cleaned = cleaned[1:]

    # If the string has dots as thousands separators and optionally comma as decimal:
    # 1.234.567,89 → 1234567.89
    if "." in cleaned and "," in cleaned:
        cleaned = cleaned.replace(".", "")
        cleaned = cleaned.replace(",", ".")
    elif "." in cleaned:
        # Could be thousands separator (1.234.567) or decimal (1234.56)
        # Techcombank uses dot as thousands separator for VND
        parts = cleaned.split(".")
        if all(len(p) == 3 for p in parts[1:]):
            # All parts after first have 3 digits → thousands separator
            cleaned = cleaned.replace(".", "")
        # else keep as-is (decimal point)
    elif "," in cleaned:
        # Comma as decimal separator
        cleaned = cleaned.replace(",", ".")

    try:
        amount = Decimal(cleaned)
        return -amount if negative else amount
    except InvalidOperation:
        return None


def parse_date(text: str) -> date | None:
    """Parse a date string in DD/MM/YYYY or DD-MM-YYYY format.

    Also handles DD/MM/YY.
    """
    if not text:
        return None

    cleaned = text.strip()

    patterns = [
        (r"(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})", False),  # DD/MM/YYYY
        (r"(\d{1,2})[/\-](\d{1,2})[/\-](\d{2})", True),  # DD/MM/YY
    ]

    for pattern, short_year in patterns:
        match = re.search(pattern, cleaned)
        if match:
            day, month, year = int(match.group(1)), int(match.group(2)), int(match.group(3))
            if short_year:
                year += 2000 if year < 50 else 1900
            try:
                return date(year, month, day)
            except ValueError:
                continue

    return None


def normalize_vietnamese_text(text: str) -> str:
    """Normalize Vietnamese Unicode text.

    Ensures consistent Unicode normalization (NFC form) and cleans up
    common OCR artifacts.
    """
    if not text:
        return ""

    # NFC normalization for Vietnamese diacritics
    text = unicodedata.normalize("NFC", text)

    # Common OCR substitution fixes
    ocr_fixes = {
        "đ ": "đ",
        " ̃": "̃",  # combining tilde spacing issue
        "Đ ": "Đ",
    }
    for bad, good in ocr_fixes.items():
        text = text.replace(bad, good)

    # Collapse multiple spaces
    text = re.sub(r"\s+", " ", text).strip()

    return text


def detect_transaction_type(amount_text: str, description: str = "") -> str:
    """Detect if a transaction is debit or credit.

    Credits are indicated by negative amounts, "CR" suffix, or keywords like
    "Hoàn tiền" (refund), "Thanh toán" (payment).
    """
    credit_keywords = ["hoàn tiền", "thanh toán", "payment", "refund", "credit", "cr"]

    # Check for credit indicators in amount
    if amount_text.strip().startswith("-") or amount_text.strip().startswith("("):
        return "credit"
    if amount_text.strip().upper().endswith("CR"):
        return "credit"

    # Check description for credit keywords
    desc_lower = description.lower()
    for keyword in credit_keywords:
        if keyword in desc_lower:
            return "credit"

    return "debit"
