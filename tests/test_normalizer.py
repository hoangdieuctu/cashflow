"""Tests for the normalizer module."""

from datetime import date
from decimal import Decimal

from cashflow.parser.normalizer import (
    detect_transaction_type,
    normalize_vietnamese_text,
    parse_date,
    parse_vnd_amount,
)


class TestParseVndAmount:
    def test_simple_number(self):
        assert parse_vnd_amount("1234567") == Decimal("1234567")

    def test_dot_thousands_separator(self):
        assert parse_vnd_amount("1.234.567") == Decimal("1234567")

    def test_dot_thousands_comma_decimal(self):
        assert parse_vnd_amount("1.234.567,89") == Decimal("1234567.89")

    def test_with_currency_label(self):
        assert parse_vnd_amount("1.234.567 VND") == Decimal("1234567")

    def test_negative_parentheses(self):
        assert parse_vnd_amount("(500.000)") == Decimal("-500000")

    def test_negative_dash(self):
        assert parse_vnd_amount("-500.000") == Decimal("-500000")

    def test_empty_string(self):
        assert parse_vnd_amount("") is None

    def test_none(self):
        assert parse_vnd_amount("") is None

    def test_with_spaces(self):
        assert parse_vnd_amount(" 1.000.000 ") == Decimal("1000000")

    def test_single_dot_decimal(self):
        # e.g. USD amount like 123.45
        assert parse_vnd_amount("123.45") == Decimal("123.45")


class TestParseDate:
    def test_dd_mm_yyyy_slash(self):
        assert parse_date("15/01/2024") == date(2024, 1, 15)

    def test_dd_mm_yyyy_dash(self):
        assert parse_date("15-01-2024") == date(2024, 1, 15)

    def test_dd_mm_yy(self):
        assert parse_date("15/01/24") == date(2024, 1, 15)

    def test_with_surrounding_text(self):
        assert parse_date("Date: 15/01/2024 ") == date(2024, 1, 15)

    def test_empty(self):
        assert parse_date("") is None

    def test_invalid(self):
        assert parse_date("99/99/9999") is None


class TestNormalizeVietnameseText:
    def test_collapse_spaces(self):
        assert normalize_vietnamese_text("Hello   World") == "Hello World"

    def test_strip(self):
        assert normalize_vietnamese_text("  Xin chào  ") == "Xin chào"

    def test_empty(self):
        assert normalize_vietnamese_text("") == ""

    def test_unicode_normalization(self):
        # Composed vs decomposed Vietnamese characters
        text = "Nguyễn Văn A"
        result = normalize_vietnamese_text(text)
        assert "Nguyễn" in result


class TestDetectTransactionType:
    def test_negative_amount(self):
        assert detect_transaction_type("-500.000") == "credit"

    def test_parentheses_amount(self):
        assert detect_transaction_type("(500.000)") == "credit"

    def test_cr_suffix(self):
        assert detect_transaction_type("500.000 CR") == "credit"

    def test_payment_description(self):
        assert detect_transaction_type("500.000", "Thanh toán qua ngân hàng") == "credit"

    def test_refund_description(self):
        assert detect_transaction_type("500.000", "Hoàn tiền giao dịch") == "credit"

    def test_normal_debit(self):
        assert detect_transaction_type("500.000", "GRAB*GRABFOOD") == "debit"
