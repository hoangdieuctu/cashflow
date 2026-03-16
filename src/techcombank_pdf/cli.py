"""Click CLI for Techcombank PDF statement parser."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from techcombank_pdf.config import OUTPUT_DIR, SAMPLES_DIR


@click.group()
@click.version_option(package_name="techcombank-pdf")
def cli():
    """Techcombank Credit Card PDF Statement Parser."""


@cli.command()
@click.argument("pdf_path", type=click.Path(exists=True, path_type=Path))
@click.option("--output-dir", "-o", type=click.Path(path_type=Path), default=None)
@click.option("--dpi", type=int, default=300)
@click.option("--format", "image_format", type=click.Choice(["png", "jpeg"]), default="png")
@click.option("--pages", type=str, default=None, help="Page numbers (comma-separated, 1-indexed)")
def convert(pdf_path: Path, output_dir: Path | None, dpi: int, image_format: str, pages: str | None):
    """Convert PDF pages to images."""
    from techcombank_pdf.converter.pdf_to_image import convert_pdf_to_images

    page_list = None
    if pages:
        page_list = [int(p.strip()) - 1 for p in pages.split(",")]

    image_paths = convert_pdf_to_images(
        pdf_path, output_dir=output_dir, dpi=dpi, image_format=image_format, pages=page_list
    )

    click.echo(f"Converted {len(image_paths)} pages:")
    for p in image_paths:
        click.echo(f"  {p}")


@cli.command()
@click.argument("pdf_path", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--output-format", "-f",
    type=click.Choice(["excel", "csv", "json", "all"]),
    default="excel",
)
@click.option("--output-dir", "-o", type=click.Path(path_type=Path), default=None)
@click.option("--force-ocr", is_flag=True, help="Force OCR instead of text extraction")
def parse(pdf_path: Path, output_format: str, output_dir: Path | None, force_ocr: bool):
    """Parse a PDF statement and export results."""
    from techcombank_pdf.exporter.csv_exporter import export_csv
    from techcombank_pdf.exporter.excel_exporter import export_excel
    from techcombank_pdf.exporter.json_exporter import export_json
    from techcombank_pdf.parser.statement_parser import parse_statement

    output_dir = output_dir or OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = pdf_path.stem

    result = parse_statement(pdf_path, force_ocr=force_ocr)

    click.echo(f"Parsed {result.transaction_count} transactions ({result.parse_method})")

    if result.warnings:
        for w in result.warnings:
            click.secho(f"  Warning: {w}", fg="yellow")

    formats = ["excel", "csv", "json"] if output_format == "all" else [output_format]

    for fmt in formats:
        if fmt == "excel":
            path = export_excel(result, output_dir / f"{stem}.xlsx")
            click.echo(f"  Excel: {path}")
        elif fmt == "csv":
            path = export_csv(result, output_dir / f"{stem}.csv")
            click.echo(f"  CSV: {path}")
        elif fmt == "json":
            path = export_json(result, output_dir / f"{stem}.json")
            click.echo(f"  JSON: {path}")


@cli.command("import")
@click.argument("pdf_path", type=click.Path(exists=True, path_type=Path))
@click.option("--db", type=click.Path(path_type=Path), default=None, help="Database path")
@click.option("--force-ocr", is_flag=True)
def import_cmd(pdf_path: Path, db: Path | None, force_ocr: bool):
    """Parse a PDF and import into the SQLite database."""
    from techcombank_pdf.database.repository import Repository
    from techcombank_pdf.parser.statement_parser import parse_statement

    result = parse_statement(pdf_path, force_ocr=force_ocr)
    click.echo(f"Parsed {result.transaction_count} transactions ({result.parse_method})")

    with Repository(str(db) if db else None) as repo:
        stmt_id = repo.import_parse_result(result)
        click.echo(f"Imported as statement #{stmt_id}")


@cli.command()
@click.option("--start-date", type=str, default=None, help="Start date (YYYY-MM-DD)")
@click.option("--end-date", type=str, default=None, help="End date (YYYY-MM-DD)")
@click.option("--type", "txn_type", type=click.Choice(["debit", "credit"]), default=None)
@click.option("--search", "-s", type=str, default=None)
@click.option("--limit", type=int, default=50)
@click.option("--db", type=click.Path(path_type=Path), default=None)
@click.option("--summary", is_flag=True, help="Show spending summary instead")
def query(start_date, end_date, txn_type, search, limit, db, summary):
    """Query transactions from the database."""
    from techcombank_pdf.database.repository import Repository

    with Repository(str(db) if db else None) as repo:
        if summary:
            data = repo.get_spending_summary()
            click.echo(f"Total transactions: {data['total_transactions']}")
            click.echo(f"Total debit:  {data['total_debit']:,.0f} VND")
            click.echo(f"Total credit: {data['total_credit']:,.0f} VND")
            click.echo(f"Net:          {data['total_debit'] - data['total_credit']:,.0f} VND")

            if data["monthly"]:
                click.echo("\nMonthly breakdown:")
                for m in data["monthly"]:
                    click.echo(f"  {m['month']}: {m['spending']:,.0f} VND ({m['count']} txns)")
            return

        transactions = repo.get_transactions(
            start_date=start_date,
            end_date=end_date,
            transaction_type=txn_type,
            search=search,
            limit=limit,
        )

        if not transactions:
            click.echo("No transactions found.")
            return

        click.echo(f"Found {len(transactions)} transactions:\n")
        for txn in transactions:
            type_marker = "+" if txn["transaction_type"] == "credit" else "-"
            click.echo(
                f"  {txn['transaction_date']}  {type_marker}{txn['billing_amount_vnd']:>12} VND  {txn['description'][:50]}"
            )


@cli.command()
@click.option("--host", default="127.0.0.1")
@click.option("--port", default=5000, type=int)
@click.option("--debug", is_flag=True)
@click.option("--db", type=click.Path(path_type=Path), default=None)
def serve(host: str, port: int, debug: bool, db: str | None):
    """Start the web dashboard."""
    from techcombank_pdf.web.app import create_app

    app = create_app(db_path=str(db) if db else None)
    click.echo(f"Starting dashboard at http://{host}:{port}")
    app.run(host=host, port=port, debug=debug)
