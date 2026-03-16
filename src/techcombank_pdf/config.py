"""Configuration constants and paths."""

from pathlib import Path

# Project root is two levels up from this file (src/techcombank_pdf/config.py)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Data directories
DATA_DIR = PROJECT_ROOT / "data"
SAMPLES_DIR = DATA_DIR / "samples"
OUTPUT_DIR = DATA_DIR / "output"

# Database
DATABASE_PATH = PROJECT_ROOT / "techcombank.db"

# PDF to image conversion
DEFAULT_DPI = 300
DEFAULT_IMAGE_FORMAT = "png"

# Techcombank statement patterns
STATEMENT_HEADER_PATTERNS = [
    "TECHCOMBANK",
    "Ngân hàng TMCP Kỹ Thương Việt Nam",
    "SÀO KÊ THẺ TÍN DỤNG",
    "SAO KÊ THẺ TÍN DỤNG",
    "CREDIT CARD STATEMENT",
]

# Table column headers — Techcombank statements use these
TABLE_HEADER_PATTERNS = {
    "transaction_date": ["Ngày giao dịch", "Transaction Date", "NGÀY GD"],
    "posting_date": ["Ngày hạch toán", "Posting Date", "NGÀY HT"],
    "description": ["Mô tả", "Description", "NỘI DUNG"],
    "amount": ["Số tiền", "Amount", "SỐ TIỀN"],
    "currency": ["Loại tiền", "Currency"],
}

# OCR settings
OCR_LANGUAGES = "vie+eng"
OCR_DPI = 300

# VND formatting: dot as thousands separator, comma as decimal (rarely used)
VND_THOUSANDS_SEP = "."
VND_DECIMAL_SEP = ","
