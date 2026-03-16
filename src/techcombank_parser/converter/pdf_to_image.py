"""Convert PDF pages to images using PyMuPDF."""

from __future__ import annotations

from pathlib import Path

import fitz  # PyMuPDF

from techcombank_parser.config import DEFAULT_DPI, DEFAULT_IMAGE_FORMAT, OUTPUT_DIR


def convert_pdf_to_images(
    pdf_path: str | Path,
    output_dir: str | Path | None = None,
    dpi: int = DEFAULT_DPI,
    image_format: str = DEFAULT_IMAGE_FORMAT,
    pages: list[int] | None = None,
    password: str | None = None,
) -> list[Path]:
    """Convert PDF pages to images.

    Args:
        pdf_path: Path to the PDF file.
        output_dir: Directory for output images. Defaults to data/output/.
        dpi: Resolution in dots per inch.
        image_format: Output format ('png' or 'jpeg').
        pages: Specific page numbers (0-indexed) to convert. None = all pages.
        password: Password for encrypted PDFs.

    Returns:
        List of paths to generated image files.
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    output_dir = Path(output_dir) if output_dir else OUTPUT_DIR / pdf_path.stem
    output_dir.mkdir(parents=True, exist_ok=True)

    zoom = dpi / 72  # PDF base resolution is 72 DPI
    matrix = fitz.Matrix(zoom, zoom)

    image_paths: list[Path] = []
    doc = fitz.open(str(pdf_path))
    if password and doc.is_encrypted:
        if not doc.authenticate(password):
            doc.close()
            raise ValueError("Invalid PDF password")

    try:
        page_range = pages if pages is not None else range(doc.page_count)

        for page_num in page_range:
            if page_num < 0 or page_num >= doc.page_count:
                continue

            page = doc[page_num]
            pix = page.get_pixmap(matrix=matrix)

            ext = "jpg" if image_format.lower() == "jpeg" else image_format.lower()
            output_path = output_dir / f"page_{page_num + 1:03d}.{ext}"

            if ext == "jpg":
                pix.save(str(output_path), jpg_quality=95)
            else:
                pix.save(str(output_path))

            image_paths.append(output_path)
    finally:
        doc.close()

    return image_paths


def get_page_count(pdf_path: str | Path) -> int:
    """Return the number of pages in a PDF."""
    doc = fitz.open(str(pdf_path))
    count = doc.page_count
    doc.close()
    return count
