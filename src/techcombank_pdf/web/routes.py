"""Flask routes for the web dashboard."""

from __future__ import annotations

import tempfile
from pathlib import Path

from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)

from techcombank_pdf.config import OUTPUT_DIR

bp = Blueprint("main", __name__)


def _get_repo():
    from techcombank_pdf.database.repository import Repository
    return Repository(current_app.config["DB_PATH"])


@bp.route("/")
def index():
    """Dashboard home page."""
    with _get_repo() as repo:
        summary = repo.get_spending_summary()
        statements = repo.get_statements()
        recent = repo.get_transactions(limit=10)
    return render_template(
        "dashboard.html",
        summary=summary,
        statements=statements,
        recent_transactions=recent,
    )


@bp.route("/upload", methods=["GET", "POST"])
def upload():
    """Upload and parse a PDF statement."""
    if request.method == "GET":
        return render_template("upload.html")

    file = request.files.get("pdf_file")
    if not file or not file.filename or not file.filename.lower().endswith(".pdf"):
        flash("Please upload a valid PDF file.", "error")
        return redirect(url_for("main.upload"))

    # Save uploaded file to temp location
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        file.save(tmp.name)
        tmp_path = Path(tmp.name)

    try:
        from techcombank_pdf.parser.statement_parser import parse_statement

        force_ocr = request.form.get("force_ocr") == "on"
        result = parse_statement(tmp_path, force_ocr=force_ocr)
        result.metadata.source_file = file.filename

        with _get_repo() as repo:
            stmt_id = repo.import_parse_result(result)

        flash(
            f"Successfully imported {result.transaction_count} transactions "
            f"from {file.filename} (method: {result.parse_method}).",
            "success",
        )

        if result.warnings:
            for w in result.warnings:
                flash(w, "warning")

    except Exception as e:
        flash(f"Error parsing PDF: {e}", "error")
    finally:
        tmp_path.unlink(missing_ok=True)

    return redirect(url_for("main.index"))


@bp.route("/transactions")
def transactions():
    """Transaction list with filtering."""
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    txn_type = request.args.get("type")
    search = request.args.get("search")
    page = int(request.args.get("page", 1))
    per_page = 50

    with _get_repo() as repo:
        txns = repo.get_transactions(
            start_date=start_date,
            end_date=end_date,
            transaction_type=txn_type,
            search=search,
            limit=per_page,
            offset=(page - 1) * per_page,
        )
        total = repo.get_transaction_count()

    total_pages = max(1, (total + per_page - 1) // per_page)

    return render_template(
        "transactions.html",
        transactions=txns,
        page=page,
        total_pages=total_pages,
        total=total,
        filters={
            "start_date": start_date or "",
            "end_date": end_date or "",
            "type": txn_type or "",
            "search": search or "",
        },
    )


@bp.route("/api/summary")
def api_summary():
    """API endpoint for dashboard chart data."""
    with _get_repo() as repo:
        summary = repo.get_spending_summary()
    return jsonify(summary)


@bp.route("/api/transactions")
def api_transactions():
    """API endpoint for transactions (JSON)."""
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    txn_type = request.args.get("type")
    search = request.args.get("search")
    limit = int(request.args.get("limit", 500))

    with _get_repo() as repo:
        txns = repo.get_transactions(
            start_date=start_date,
            end_date=end_date,
            transaction_type=txn_type,
            search=search,
            limit=limit,
        )
    return jsonify(txns)


@bp.route("/export/<fmt>")
def export(fmt: str):
    """Export all transactions to the requested format."""
    from techcombank_pdf.exporter.csv_exporter import export_csv
    from techcombank_pdf.exporter.excel_exporter import export_excel
    from techcombank_pdf.exporter.json_exporter import export_json
    from techcombank_pdf.models.transaction import ParseResult, StatementMetadata

    with _get_repo() as repo:
        txns_raw = repo.get_transactions(limit=10000)

    # Build a ParseResult from DB data
    from techcombank_pdf.models.transaction import Transaction, TransactionType
    from techcombank_pdf.parser.normalizer import parse_date
    from decimal import Decimal
    from datetime import date

    transactions = []
    for t in txns_raw:
        txn_date = date.fromisoformat(t["transaction_date"]) if t["transaction_date"] else date.today()
        post_date = date.fromisoformat(t["posting_date"]) if t.get("posting_date") else None
        transactions.append(Transaction(
            transaction_date=txn_date,
            posting_date=post_date,
            description=t["description"],
            original_amount=Decimal(t["original_amount"]),
            original_currency=t.get("original_currency", "VND"),
            billing_amount_vnd=Decimal(t["billing_amount_vnd"]),
            transaction_type=TransactionType(t["transaction_type"]),
            category=t.get("category"),
            merchant_name=t.get("merchant_name"),
            card_last_four=t.get("card_last_four"),
            reference_number=t.get("reference_number"),
        ))

    result = ParseResult(
        metadata=StatementMetadata(source_file="export"),
        transactions=transactions,
    )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if fmt == "excel":
        path = export_excel(result, OUTPUT_DIR / "export.xlsx")
        return send_file(str(path), as_attachment=True, download_name="transactions.xlsx")
    elif fmt == "csv":
        path = export_csv(result, OUTPUT_DIR / "export.csv")
        return send_file(str(path), as_attachment=True, download_name="transactions.csv")
    elif fmt == "json":
        path = export_json(result, OUTPUT_DIR / "export.json")
        return send_file(str(path), as_attachment=True, download_name="transactions.json")
    else:
        flash("Unknown export format.", "error")
        return redirect(url_for("main.index"))
