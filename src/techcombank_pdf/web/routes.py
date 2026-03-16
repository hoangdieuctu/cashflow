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
    url_for,
)

bp = Blueprint("main", __name__)


def _get_repo():
    from techcombank_pdf.database.repository import Repository
    return Repository(current_app.config["DB_PATH"])


@bp.route("/", methods=["GET", "POST"])
def index():
    """Single-page dashboard with upload, stats, charts, and transactions."""
    # Handle PDF upload
    if request.method == "POST":
        file = request.files.get("pdf_file")
        if not file or not file.filename or not file.filename.lower().endswith(".pdf"):
            flash("Please upload a valid PDF file.", "error")
            return redirect(url_for("main.index"))

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            file.save(tmp.name)
            tmp_path = Path(tmp.name)

        try:
            from techcombank_pdf.parser.statement_parser import parse_statement

            password = request.form.get("password") or None
            result = parse_statement(tmp_path, password=password)
            result.metadata.source_file = file.filename

            if result.transaction_count == 0:
                flash(
                    f"No transactions found in {file.filename}. "
                    "The PDF may be password-protected (enter the password above) "
                    "or the statement format is not yet supported.",
                    "warning",
                )
                return redirect(url_for("main.index"))

            with _get_repo() as repo:
                repo.import_parse_result(result)

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

    # GET — render full dashboard
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    txn_type = request.args.get("type")
    category = request.args.get("category")
    search = request.args.get("search")
    page = int(request.args.get("page", 1))
    per_page = 50

    with _get_repo() as repo:
        summary = repo.get_spending_summary()
        statements = repo.get_statements()
        txns = repo.get_transactions(
            start_date=start_date,
            end_date=end_date,
            transaction_type=txn_type,
            category=category,
            search=search,
            limit=per_page,
            offset=(page - 1) * per_page,
        )
        total = repo.get_transaction_count()
        categories = repo.get_all_categories()
        category_summary = repo.get_category_monthly_summary()

    total_pages = max(1, (total + per_page - 1) // per_page)

    return render_template(
        "dashboard.html",
        summary=summary,
        statements=statements,
        transactions=txns,
        total=total,
        page=page,
        total_pages=total_pages,
        categories=categories,
        category_summary=category_summary,
        filters={
            "start_date": start_date or "",
            "end_date": end_date or "",
            "type": txn_type or "",
            "category": category or "",
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


@bp.route("/api/transaction/<int:txn_id>/category", methods=["POST"])
def update_category(txn_id: int):
    """Update a transaction's category."""
    data = request.get_json()
    if data is None:
        return jsonify({"error": "JSON body required"}), 400

    category = (data.get("category") or "").strip() or None
    apply_to_merchant = data.get("apply_to_merchant", False)

    with _get_repo() as repo:
        ok = repo.update_transaction_category(txn_id, category)
        if not ok:
            return jsonify({"error": "Transaction not found"}), 404

        updated_count = 1
        if apply_to_merchant and category:
            # Get the merchant_name of this transaction
            row = repo.conn.execute(
                "SELECT merchant_name FROM transactions WHERE id = ?", (txn_id,)
            ).fetchone()
            if row and row["merchant_name"]:
                updated_count = repo.update_category_by_merchant(
                    row["merchant_name"], category
                )

    return jsonify({"ok": True, "category": category, "updated_count": updated_count})
