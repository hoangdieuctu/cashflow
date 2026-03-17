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
    from techcombank_parser.database.repository import Repository
    return Repository(current_app.config["DB_PATH"])


@bp.route("/")
def index():
    """Single-page dashboard with stats, charts, and transactions."""
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    txn_type = request.args.get("type")
    category = request.args.get("category")
    statement_id_str = request.args.get("statement_id")
    statement_id = int(statement_id_str) if statement_id_str else None
    statement_type = request.args.get("statement_type")
    search = request.args.get("search")
    page = int(request.args.get("page", 1))
    per_page = 50

    with _get_repo() as repo:
        all_statements = repo.get_statements()

        # Filter statements list by card type for the dropdown
        if statement_type:
            filtered_statements = [s for s in all_statements if s["statement_type"] == statement_type]
        else:
            filtered_statements = all_statements

        # Clear statement_id if it doesn't belong to the selected card type
        if statement_id and statement_type:
            match = next((s for s in all_statements if s["id"] == statement_id), None)
            if match and match["statement_type"] != statement_type:
                statement_id = None
                statement_id_str = ""

        summary = repo.get_spending_summary(statement_id=statement_id, category=category)
        txns = repo.get_transactions(
            start_date=start_date,
            end_date=end_date,
            transaction_type=txn_type,
            category=category,
            search=search,
            statement_id=statement_id,
            statement_type=statement_type,
            limit=per_page,
            offset=(page - 1) * per_page,
        )
        total = repo.get_transaction_count(statement_id=statement_id, category=category, search=search, statement_type=statement_type)
        categories = repo.get_all_categories()
        category_summary = repo.get_category_monthly_summary(statement_id=statement_id, category=category)

    total_pages = max(1, (total + per_page - 1) // per_page)

    return render_template(
        "dashboard.html",
        summary=summary,
        statements=filtered_statements,
        has_any_statements=len(all_statements) > 0,
        total_statements=len(all_statements),
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
            "statement_id": statement_id_str or "",
            "statement_type": statement_type or "",
            "search": search or "",
        },
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

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        file.save(tmp.name)
        tmp_path = Path(tmp.name)

    try:
        from techcombank_parser.parser.statement_parser import parse_statement

        password = request.form.get("password") or None
        result = parse_statement(tmp_path, password=password)
        result.metadata.source_file = file.filename

        if result.transaction_count == 0:
            flash(
                f"No transactions found in {file.filename}. "
                "The PDF may be password-protected (enter the password above) "
                "or the statement format is not yet supported. "
                "Supported formats: Techcombank credit card statements and bank account statements (SaoKeTK_...).",
                "warning",
            )
            return redirect(url_for("main.upload"))

        with _get_repo() as repo:
            # Check if this statement was already imported
            existing = repo.conn.execute(
                "SELECT id FROM statements WHERE source_file = ?",
                (file.filename,),
            ).fetchone()
            if existing:
                flash(
                    f"{file.filename} has already been imported.",
                    "error",
                )
                return redirect(url_for("main.upload"))

            repo.import_parse_result(result)

        stmt_type_label = (
            "bank account (debit card)"
            if result.metadata.statement_type.value == "bank_account"
            else "credit card"
        )
        flash(
            f"Successfully imported {result.transaction_count} transactions "
            f"from {file.filename} ({stmt_type_label}).",
            "success",
        )

        if result.warnings:
            for w in result.warnings:
                flash(w, "warning")

    except Exception as e:
        flash(f"Error parsing PDF: {e}", "error")
        return redirect(url_for("main.upload"))
    finally:
        tmp_path.unlink(missing_ok=True)

    return redirect(url_for("main.index"))


@bp.route("/rules", methods=["GET"])
def rules():
    """Category rules management page."""
    with _get_repo() as repo:
        all_rules = repo.get_rules()
        categories = repo.get_all_categories()
    return render_template("rules.html", rules=all_rules, categories=categories)


@bp.route("/api/rules", methods=["POST"])
def add_rule():
    """Add a new category rule."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400

    match_type = data.get("match_type", "").strip()
    pattern = data.get("pattern", "").strip()
    category = data.get("category", "").strip()
    priority = int(data.get("priority", 0))

    if match_type not in ("contains", "endswith"):
        return jsonify({"error": "match_type must be 'contains' or 'endswith'"}), 400
    if not pattern or not category:
        return jsonify({"error": "pattern and category are required"}), 400

    with _get_repo() as repo:
        rule_id = repo.add_rule(match_type, pattern, category, priority)
    return jsonify({"ok": True, "id": rule_id})


@bp.route("/api/rules/<int:rule_id>", methods=["DELETE"])
def delete_rule(rule_id: int):
    """Delete a category rule."""
    with _get_repo() as repo:
        ok = repo.delete_rule(rule_id)
    if not ok:
        return jsonify({"error": "Rule not found"}), 404
    return jsonify({"ok": True})


@bp.route("/api/rules/apply", methods=["POST"])
def apply_rules():
    """Apply all rules to uncategorized transactions."""
    with _get_repo() as repo:
        count = repo.apply_rules()
    return jsonify({"ok": True, "updated": count})


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
