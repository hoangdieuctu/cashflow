"""Tests for exporters."""

import csv
import json
from pathlib import Path

from techcombank_pdf.exporter.csv_exporter import export_csv
from techcombank_pdf.exporter.excel_exporter import export_excel
from techcombank_pdf.exporter.json_exporter import export_json


class TestExcelExporter:
    def test_creates_file(self, sample_parse_result, tmp_dir):
        path = export_excel(sample_parse_result, tmp_dir / "test.xlsx")
        assert path.exists()
        assert path.suffix == ".xlsx"

    def test_file_has_content(self, sample_parse_result, tmp_dir):
        path = export_excel(sample_parse_result, tmp_dir / "test.xlsx")
        assert path.stat().st_size > 0


class TestCsvExporter:
    def test_creates_file(self, sample_parse_result, tmp_dir):
        path = export_csv(sample_parse_result, tmp_dir / "test.csv")
        assert path.exists()
        assert path.suffix == ".csv"

    def test_utf8_bom(self, sample_parse_result, tmp_dir):
        path = export_csv(sample_parse_result, tmp_dir / "test.csv")
        raw = path.read_bytes()
        assert raw[:3] == b"\xef\xbb\xbf"  # UTF-8 BOM

    def test_row_count(self, sample_parse_result, tmp_dir):
        path = export_csv(sample_parse_result, tmp_dir / "test.csv")
        with open(path, encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            rows = list(reader)
        # Header + 3 transactions
        assert len(rows) == 4

    def test_vietnamese_content(self, sample_parse_result, tmp_dir):
        path = export_csv(sample_parse_result, tmp_dir / "test.csv")
        content = path.read_text(encoding="utf-8-sig")
        assert "Hoàn tiền" in content


class TestJsonExporter:
    def test_creates_file(self, sample_parse_result, tmp_dir):
        path = export_json(sample_parse_result, tmp_dir / "test.json")
        assert path.exists()

    def test_valid_json(self, sample_parse_result, tmp_dir):
        path = export_json(sample_parse_result, tmp_dir / "test.json")
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        assert "transactions" in data
        assert len(data["transactions"]) == 3

    def test_metadata_included(self, sample_parse_result, tmp_dir):
        path = export_json(sample_parse_result, tmp_dir / "test.json")
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        assert data["metadata"]["source_file"] == "test_statement.pdf"
