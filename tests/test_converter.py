"""Tests for PDF to image converter."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from techcombank_pdf.converter.pdf_to_image import convert_pdf_to_images, get_page_count


class TestConvertPdfToImages:
    def test_file_not_found(self, tmp_dir):
        with pytest.raises(FileNotFoundError):
            convert_pdf_to_images(tmp_dir / "nonexistent.pdf")

    @patch("techcombank_pdf.converter.pdf_to_image.fitz")
    def test_converts_all_pages(self, mock_fitz, tmp_dir):
        # Mock PDF document
        mock_doc = MagicMock()
        mock_doc.page_count = 3
        mock_page = MagicMock()
        mock_pix = MagicMock()
        mock_page.get_pixmap.return_value = mock_pix
        mock_doc.__getitem__ = MagicMock(return_value=mock_page)
        mock_fitz.open.return_value = mock_doc
        mock_fitz.Matrix = MagicMock()

        # Create a dummy PDF file so the existence check passes
        pdf_path = tmp_dir / "test.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 dummy")

        output_dir = tmp_dir / "output"
        result = convert_pdf_to_images(pdf_path, output_dir=output_dir)

        assert len(result) == 3
        assert mock_pix.save.call_count == 3

    @patch("techcombank_pdf.converter.pdf_to_image.fitz")
    def test_specific_pages(self, mock_fitz, tmp_dir):
        mock_doc = MagicMock()
        mock_doc.page_count = 5
        mock_page = MagicMock()
        mock_pix = MagicMock()
        mock_page.get_pixmap.return_value = mock_pix
        mock_doc.__getitem__ = MagicMock(return_value=mock_page)
        mock_fitz.open.return_value = mock_doc
        mock_fitz.Matrix = MagicMock()

        pdf_path = tmp_dir / "test.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 dummy")

        result = convert_pdf_to_images(pdf_path, output_dir=tmp_dir / "out", pages=[0, 2])
        assert len(result) == 2
