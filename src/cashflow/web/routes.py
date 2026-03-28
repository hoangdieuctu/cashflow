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
    session,
    url_for,
)

bp = Blueprint("main", __name__)


def _get_repo():
    from cashflow.database.repository import Repository
    return Repository(current_app.config["DB_PATH"])


@bp.route("/lock/now")
def lock_now():
    session.pop("authenticated_at", None)
    return redirect(url_for("main.lock"))


@bp.route("/lock", methods=["GET", "POST"])
def lock():
    from datetime import datetime, timezone
    if request.method == "POST":
        import hashlib
        entered = request.form.get("passcode", "")
        with _get_repo() as repo:
            stored_hash = repo.get_setting("passcode_hash")
        entered_hash = hashlib.sha256(entered.encode()).hexdigest()
        if stored_hash and entered_hash == stored_hash:
            session["authenticated_at"] = datetime.now(timezone.utc).timestamp()
            next_url = request.args.get("next") or url_for("main.index")
            return redirect(next_url)
        return render_template("lock.html", error=True)
    return render_template("lock.html", error=False)


@bp.route("/settings")
def settings():
    with _get_repo() as repo:
        enabled = repo.get_setting("passcode_enabled") == "1"
        has_passcode = repo.get_setting("passcode_hash") is not None
        backup_email_config = {
            "smtp_host": repo.get_setting("backup_smtp_host") or "",
            "smtp_port": repo.get_setting("backup_smtp_port") or "465",
            "smtp_user": repo.get_setting("backup_smtp_user") or "",
            "recipient": repo.get_setting("backup_recipient") or "",
        }
    return render_template("settings.html", passcode_enabled=enabled, has_passcode=has_passcode, backup_email_config=backup_email_config)


@bp.route("/api/settings/backup-email", methods=["POST"])
def save_backup_email_config():
    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400
    smtp_host = (data.get("smtp_host") or "").strip()
    smtp_port = (data.get("smtp_port") or "587").strip()
    smtp_user = (data.get("smtp_user") or "").strip()
    smtp_pass = (data.get("smtp_pass") or "").strip()
    recipient = (data.get("recipient") or "").strip()
    if not smtp_host or not smtp_user or not recipient:
        return jsonify({"error": "SMTP host, username, and recipient are required"}), 400
    try:
        int(smtp_port)
    except ValueError:
        return jsonify({"error": "SMTP port must be a number"}), 400
    with _get_repo() as repo:
        repo.set_setting("backup_smtp_host", smtp_host)
        repo.set_setting("backup_smtp_port", smtp_port)
        repo.set_setting("backup_smtp_user", smtp_user)
        if smtp_pass:
            repo.set_setting("backup_smtp_pass", smtp_pass)
        repo.set_setting("backup_recipient", recipient)
    return jsonify({"ok": True})


@bp.route("/api/backup/send", methods=["POST"])
def send_backup():
    import shutil
    import smtplib
    import tempfile
    from datetime import date
    from email import encoders
    from email.mime.base import MIMEBase
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    from cashflow import __version__
    from cashflow.config import DATABASE_PATH

    with _get_repo() as repo:
        smtp_host = repo.get_setting("backup_smtp_host")
        smtp_port = int(repo.get_setting("backup_smtp_port") or 587)
        smtp_user = repo.get_setting("backup_smtp_user")
        smtp_pass = repo.get_setting("backup_smtp_pass")
        recipient = repo.get_setting("backup_recipient")

    if not smtp_host or not smtp_user or not recipient:
        return jsonify({"error": "Email backup is not configured. Please save SMTP settings first."}), 400

    filename = f"cashflow-{__version__}-{date.today().strftime('%Y%m%d')}.db"

    try:
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            tmp_path = tmp.name
        shutil.copy2(str(DATABASE_PATH), tmp_path)

        msg = MIMEMultipart()
        msg["From"] = smtp_user
        msg["To"] = recipient
        msg["Subject"] = f"Cashflow DB Backup — {date.today().strftime('%Y-%m-%d')}"
        msg.attach(MIMEText(f"Attached: {filename}\nVersion: {__version__}", "plain"))

        with open(tmp_path, "rb") as f:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f'attachment; filename="{filename}"')
        msg.attach(part)

        if smtp_port == 465:
            import ssl
            ctx = ssl.create_default_context()
            with smtplib.SMTP_SSL(smtp_host, smtp_port, context=ctx) as server:
                server.login(smtp_user, smtp_pass or "")
                server.sendmail(smtp_user, recipient, msg.as_string())
        else:
            with smtplib.SMTP(smtp_host, smtp_port) as server:
                server.starttls()
                server.login(smtp_user, smtp_pass or "")
                server.sendmail(smtp_user, recipient, msg.as_string())

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        import os
        try:
            os.unlink(tmp_path)
        except Exception:
            pass

    return jsonify({"ok": True, "filename": filename})


@bp.route("/api/settings/passcode", methods=["POST"])
def api_settings_passcode():
    import hashlib
    data = request.get_json()
    action = data.get("action")  # "enable", "disable", "change"

    with _get_repo() as repo:
        stored_hash = repo.get_setting("passcode_hash")
        enabled = repo.get_setting("passcode_enabled") == "1"

        if action == "enable":
            new_code = data.get("passcode", "")
            if not new_code.isdigit() or len(new_code) != 6:
                return jsonify({"error": "Passcode must be 6 digits"}), 400
            repo.set_setting("passcode_hash", hashlib.sha256(new_code.encode()).hexdigest())
            repo.set_setting("passcode_enabled", "1")
            session.pop("authenticated_at", None)

        elif action == "disable":
            current = data.get("current_passcode", "")
            if stored_hash and hashlib.sha256(current.encode()).hexdigest() != stored_hash:
                return jsonify({"error": "Incorrect passcode"}), 403
            repo.set_setting("passcode_enabled", "0")
            from datetime import datetime, timezone
            session["authenticated_at"] = datetime.now(timezone.utc).timestamp()

        elif action == "change":
            current = data.get("current_passcode", "")
            new_code = data.get("passcode", "")
            if stored_hash and hashlib.sha256(current.encode()).hexdigest() != stored_hash:
                return jsonify({"error": "Incorrect current passcode"}), 403
            if not new_code.isdigit() or len(new_code) != 6:
                return jsonify({"error": "New passcode must be 6 digits"}), 400
            repo.set_setting("passcode_hash", hashlib.sha256(new_code.encode()).hexdigest())
            session.pop("authenticated_at", None)

        else:
            return jsonify({"error": "Invalid action"}), 400

    return jsonify({"ok": True})


@bp.route("/api/settings/converters", methods=["GET"])
def get_converters():
    import json
    with _get_repo() as repo:
        raw = repo.get_setting("unit_converters")
    converters = json.loads(raw) if raw else {}
    return jsonify(converters)


@bp.route("/api/settings/converters", methods=["POST"])
def add_converter():
    import json
    data = request.get_json()
    unit = (data.get("unit") or "").strip().upper()
    rate = data.get("rate")
    if not unit:
        return jsonify({"error": "unit is required"}), 400
    try:
        rate = float(rate)
        if rate <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({"error": "rate must be a positive number"}), 400
    with _get_repo() as repo:
        raw = repo.get_setting("unit_converters")
        converters = json.loads(raw) if raw else {}
        converters[unit] = rate
        repo.set_setting("unit_converters", json.dumps(converters))
    return jsonify({"ok": True})


@bp.route("/api/settings/converters/<unit>", methods=["DELETE"])
def delete_converter(unit: str):
    import json
    unit = unit.upper()
    with _get_repo() as repo:
        raw = repo.get_setting("unit_converters")
        converters = json.loads(raw) if raw else {}
        converters.pop(unit, None)
        repo.set_setting("unit_converters", json.dumps(converters))
    return jsonify({"ok": True})


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
    period = request.args.get("period")
    # Default to current year if period not specified
    if period is None:
        from datetime import date
        period = str(date.today().year)
    period = period  # may be "" (user explicitly cleared) or "YYYY" or "YYYY-MM"
    page = int(request.args.get("page", 1))
    per_page = 50

    # Derive start_date/end_date from period
    if period and len(period) == 7:  # YYYY-MM
        import calendar
        y, m = int(period[:4]), int(period[5:7])
        last_day = calendar.monthrange(y, m)[1]
        start_date = f"{period}-01"
        end_date = f"{period}-{last_day:02d}"
    elif period and len(period) == 4:  # YYYY
        start_date = f"{period}-01-01"
        end_date = f"{period}-12-31"

    with _get_repo() as repo:
        all_statements = repo.get_statements()
        period_statements = repo.get_statements(start_date=start_date, end_date=end_date)
        period_options = repo.get_available_years_months()

        # Filter statements list by card type for the dropdown (period-scoped)
        if statement_type:
            filtered_statements = [s for s in period_statements if s["statement_type"] == statement_type]
        else:
            filtered_statements = period_statements

        # Clear statement_id if it doesn't belong to the selected card type
        if statement_id and statement_type:
            match = next((s for s in all_statements if s["id"] == statement_id), None)
            if match and match["statement_type"] != statement_type:
                statement_id = None
                statement_id_str = ""

        summary = repo.get_spending_summary(statement_id=statement_id, category=category, statement_type=statement_type, start_date=start_date, end_date=end_date)
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
        total = repo.get_transaction_count(statement_id=statement_id, category=category, search=search, statement_type=statement_type, start_date=start_date, end_date=end_date)
        categories = repo.get_all_categories(statement_id=statement_id, statement_type=statement_type, start_date=start_date, end_date=end_date)
        category_summary = repo.get_category_monthly_summary(statement_id=statement_id, category=category, statement_type=statement_type, start_date=start_date, end_date=end_date)
        fund_chart = repo.get_fund_chart_data()
        fund_balances = {f["name"]: f["balance"] for f in repo.get_fund_balances()}
        all_savings = repo.get_savings()
        dashboard_savings = [
            {
                "name": s["name"],
                "current_principal": s["current_principal"],
                "interest": s["interest"],
                "maturity_date": s["maturity_date"],
                "days_remaining": s["days_remaining"],
                "annual_rate": s["annual_rate"],
                "term_months": s["term_months"],
                "saving_type": s["saving_type"],
                "fund_name": s["fund_name"],
            }
            for s in all_savings
        ]

    total_pages = max(1, (total + per_page - 1) // per_page)

    return render_template(
        "dashboard.html",
        summary=summary,
        statements=filtered_statements,
        has_any_statements=len(all_statements) > 0,
        total_statements=len(period_statements),
        transactions=txns,
        total=total,
        page=page,
        total_pages=total_pages,
        categories=categories,
        category_summary=category_summary,
        fund_chart=fund_chart,
        fund_balances=fund_balances,
        savings=dashboard_savings,
        period_options=period_options,
        filters={
            "start_date": start_date or "",
            "end_date": end_date or "",
            "type": txn_type or "",
            "category": category or "",
            "statement_id": statement_id_str or "",
            "statement_type": statement_type or "",
            "search": search or "",
            "period": period,
        },
    )


@bp.route("/upload", methods=["GET", "POST"])
def upload():
    """Upload and parse one or more PDF statements."""
    if request.method == "GET":
        return render_template("upload.html")

    files = request.files.getlist("pdf_file")
    files = [f for f in files if f and f.filename and f.filename.lower().endswith(".pdf")]
    if not files:
        flash("Please upload at least one valid PDF file.", "error")
        return redirect(url_for("main.upload"))

    password = request.form.get("password") or None
    any_success = False

    for file in files:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            file.save(tmp.name)
            tmp_path = Path(tmp.name)

        try:
            from cashflow.parser.statement_parser import parse_statement

            result = parse_statement(tmp_path, password=password)
            result.metadata.source_file = file.filename

            if result.transaction_count == 0:
                flash(
                    f"No transactions found in {file.filename}. "
                    "The PDF may be password-protected or the format is not yet supported.",
                    "warning",
                )
                continue

            with _get_repo() as repo:
                existing = repo.conn.execute(
                    "SELECT id FROM statements WHERE source_file = ?",
                    (file.filename,),
                ).fetchone()
                if existing:
                    flash(f"{file.filename} has already been imported.", "error")
                    continue

                repo.import_parse_result(result)

            stmt_type_label = (
                "bank account (debit card)"
                if result.metadata.statement_type.value == "bank_account"
                else "credit card"
            )
            flash(
                f"Imported {result.transaction_count} transactions from {file.filename} ({stmt_type_label}).",
                "success",
            )
            if result.warnings:
                for w in result.warnings:
                    flash(w, "warning")
            any_success = True

        except Exception as e:
            flash(f"Error parsing {file.filename}: {e}", "error")
        finally:
            tmp_path.unlink(missing_ok=True)

    return redirect(url_for("main.index") if any_success else url_for("main.upload"))


@bp.route("/rules", methods=["GET"])
def rules():
    """Category rules management page."""
    with _get_repo() as repo:
        all_rules = repo.get_rules()
        categories = repo.get_all_categories()
        stats = repo.get_rule_stats()
    return render_template("rules.html", rules=all_rules, categories=categories, stats=stats)


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


@bp.route("/api/rules/<int:rule_id>", methods=["PUT"])
def update_rule(rule_id: int):
    """Update a category rule's fields."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400

    category = (data.get("category") or "").strip() or None
    match_type = (data.get("match_type") or "").strip() or None
    pattern = (data.get("pattern") or "").strip() or None
    priority = data.get("priority")

    if match_type and match_type not in ("contains", "endswith"):
        return jsonify({"error": "match_type must be 'contains' or 'endswith'"}), 400
    if priority is not None:
        priority = int(priority)

    with _get_repo() as repo:
        ok = repo.update_rule(rule_id, category=category, match_type=match_type, pattern=pattern, priority=priority)
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


# ── Funds ──────────────────────────────────────────────────────────────────────

@bp.route("/funds")
def funds():
    """Funds management page."""
    year_month = request.args.get("year_month") or None
    with _get_repo() as repo:
        balances = repo.get_fund_balances(year_month=year_month)
        salary_entries = repo.get_salary_entries()
        all_categories = repo.get_all_categories()
        period_options = repo.get_available_years_months()
        assigned = {cat for f in balances for cat in f["categories"]}
    return render_template(
        "funds.html",
        funds=balances,
        salary_entries=salary_entries,
        all_categories=all_categories,
        assigned_categories=assigned,
        period_options=period_options,
        year_month=year_month,
    )


@bp.route("/api/funds/<int:fund_id>/history")
def fund_history(fund_id: int):
    year_month = request.args.get("year_month") or None
    with _get_repo() as repo:
        events = repo.get_fund_history(fund_id, year_month=year_month)
    return jsonify(events)


@bp.route("/api/funds", methods=["POST"])
def add_fund():
    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400
    name = (data.get("name") or "").strip()
    percentage = data.get("percentage", 0)
    description = (data.get("description") or "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400
    try:
        percentage = float(percentage)
    except (TypeError, ValueError):
        return jsonify({"error": "percentage must be a number"}), 400
    with _get_repo() as repo:
        fund_id = repo.add_fund(name, percentage, description)
    return jsonify({"ok": True, "id": fund_id})


@bp.route("/api/funds/<int:fund_id>", methods=["PUT"])
def update_fund(fund_id: int):
    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400
    name = (data.get("name") or "").strip() or None
    percentage = data.get("percentage")
    description = data.get("description")
    # override_balance: not in payload = don't touch; null = clear; number = set
    override_balance = False  # sentinel: not provided
    override_reason = None
    if "override_balance" in data:
        v = data["override_balance"]
        override_balance = float(v) if v is not None else None
        override_reason = (data.get("override_reason") or "").strip() or None
    if percentage is not None:
        try:
            percentage = float(percentage)
        except (TypeError, ValueError):
            return jsonify({"error": "percentage must be a number"}), 400
    if description is not None:
        description = description.strip()
    with _get_repo() as repo:
        ok = repo.update_fund(fund_id, name=name, percentage=percentage, description=description, override_balance=override_balance, override_reason=override_reason)
    if not ok:
        return jsonify({"error": "Fund not found"}), 404
    return jsonify({"ok": True})


@bp.route("/api/funds/<int:fund_id>", methods=["DELETE"])
def delete_fund(fund_id: int):
    with _get_repo() as repo:
        ok = repo.delete_fund(fund_id)
    if not ok:
        return jsonify({"error": "Fund not found"}), 404
    return jsonify({"ok": True})


@bp.route("/api/funds/<int:fund_id>/categories", methods=["PUT"])
def set_fund_categories(fund_id: int):
    data = request.get_json()
    if not isinstance(data, dict):
        return jsonify({"error": "JSON body required"}), 400
    categories = data.get("categories", [])
    if not isinstance(categories, list):
        return jsonify({"error": "categories must be a list"}), 400
    with _get_repo() as repo:
        repo.set_fund_categories(fund_id, categories)
    return jsonify({"ok": True})


@bp.route("/api/salary", methods=["POST"])
def add_salary():
    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400
    year_month = (data.get("year_month") or "").strip()
    amount = data.get("amount")
    if not year_month or len(year_month) != 7:
        return jsonify({"error": "year_month must be YYYY-MM"}), 400
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        return jsonify({"error": "amount must be a number"}), 400
    with _get_repo() as repo:
        entry_id = repo.add_salary_entry(year_month, amount)
    return jsonify({"ok": True, "id": entry_id})


@bp.route("/api/salary/<int:entry_id>", methods=["DELETE"])
def delete_salary(entry_id: int):
    return jsonify({"error": "Salary entries cannot be deleted"}), 403


@bp.route("/api/salary/from-transactions")
def salary_from_transactions():
    """Return credit transactions with category='Salary' grouped by month."""
    with _get_repo() as repo:
        rows = repo.conn.execute(
            """SELECT substr(transaction_date, 1, 7) as year_month,
                      SUM(CAST(billing_amount_vnd AS REAL)) as amount,
                      COUNT(*) as count
               FROM transactions
               WHERE category = 'Salary' AND transaction_type = 'credit'
               GROUP BY year_month
               ORDER BY year_month DESC"""
        ).fetchall()
        existing = {e["year_month"] for e in repo.get_salary_entries()}
    return jsonify([
        {"year_month": r["year_month"], "amount": r["amount"], "count": r["count"],
         "already_imported": r["year_month"] in existing}
        for r in rows
    ])


# ── Savings ────────────────────────────────────────────────────────────────────

@bp.route("/savings")
def savings():
    """Savings management page."""
    with _get_repo() as repo:
        all_savings = repo.get_savings()
        all_funds = repo.get_funds()
    return render_template("savings.html", savings=all_savings, funds=all_funds)


@bp.route("/api/savings", methods=["POST"])
def add_saving():
    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400
    name = (data.get("name") or "").strip()
    principal = data.get("principal")
    annual_rate = data.get("annual_rate")
    term_months = data.get("term_months")
    start_date = (data.get("start_date") or "").strip()
    rollover_type = (data.get("rollover_type") or "withdraw").strip()
    note = (data.get("note") or "").strip()
    fund_id_raw = data.get("fund_id")
    fund_id = int(fund_id_raw) if fund_id_raw else None
    saving_type = (data.get("saving_type") or "fixed").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400
    if not start_date:
        return jsonify({"error": "start_date is required"}), 400
    if rollover_type not in ("withdraw", "rollover_principal", "rollover_full"):
        return jsonify({"error": "invalid rollover_type"}), 400
    if saving_type not in ("fixed", "flexible"):
        return jsonify({"error": "invalid saving_type"}), 400
    try:
        principal = float(principal)
        annual_rate = float(annual_rate)
        term_months = int(term_months)
    except (TypeError, ValueError):
        return jsonify({"error": "principal, annual_rate, term_months must be numbers"}), 400
    with _get_repo() as repo:
        saving_id = repo.add_saving(name, principal, annual_rate, term_months, start_date, rollover_type, note, fund_id, saving_type)
    return jsonify({"ok": True, "id": saving_id})


@bp.route("/api/savings/<int:saving_id>", methods=["PUT"])
def update_saving(saving_id: int):
    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400
    name = (data.get("name") or "").strip()
    principal = data.get("principal")
    annual_rate = data.get("annual_rate")
    term_months = data.get("term_months")
    start_date = (data.get("start_date") or "").strip()
    rollover_type = (data.get("rollover_type") or "withdraw").strip()
    note = (data.get("note") or "").strip()
    fund_id_raw = data.get("fund_id")
    fund_id = int(fund_id_raw) if fund_id_raw else None
    saving_type = (data.get("saving_type") or "fixed").strip()
    if not name or not start_date:
        return jsonify({"error": "name and start_date are required"}), 400
    if rollover_type not in ("withdraw", "rollover_principal", "rollover_full"):
        return jsonify({"error": "invalid rollover_type"}), 400
    if saving_type not in ("fixed", "flexible"):
        return jsonify({"error": "invalid saving_type"}), 400
    try:
        principal = float(principal)
        annual_rate = float(annual_rate)
        term_months = int(term_months)
    except (TypeError, ValueError):
        return jsonify({"error": "principal, annual_rate, term_months must be numbers"}), 400
    with _get_repo() as repo:
        ok = repo.update_saving(saving_id, name, principal, annual_rate, term_months, start_date, rollover_type, note, fund_id, saving_type)
    if not ok:
        return jsonify({"error": "Saving not found"}), 404
    return jsonify({"ok": True})


@bp.route("/api/savings/<int:saving_id>", methods=["DELETE"])
def delete_saving(saving_id: int):
    with _get_repo() as repo:
        ok = repo.delete_saving(saving_id)
    if not ok:
        return jsonify({"error": "Saving not found"}), 404
    return jsonify({"ok": True})


@bp.route("/api/savings/<int:saving_id>/withdrawals", methods=["POST"])
def add_saving_withdrawal(saving_id: int):
    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400
    w_date = (data.get("date") or "").strip()
    amount = data.get("amount")
    note = (data.get("note") or "").strip()
    if not w_date:
        return jsonify({"error": "date is required"}), 400
    try:
        amount = float(amount)
        if amount <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({"error": "amount must be a positive number"}), 400
    with _get_repo() as repo:
        wid = repo.add_saving_withdrawal(saving_id, w_date, amount, note)
    return jsonify({"ok": True, "id": wid})


@bp.route("/api/savings/<int:saving_id>/withdrawals/<int:withdrawal_id>", methods=["DELETE"])
def delete_saving_withdrawal(saving_id: int, withdrawal_id: int):
    with _get_repo() as repo:
        ok = repo.delete_saving_withdrawal(withdrawal_id)
    if not ok:
        return jsonify({"error": "Withdrawal not found"}), 404
    return jsonify({"ok": True})


# ── Extra Fees ──

@bp.route("/extra-fees")
def extra_fees():
    with _get_repo() as repo:
        fees = repo.get_extra_fees()
        for f in fees:
            f["entries"] = repo.get_extra_fee_entries(f["id"])
    return render_template("extra_fees.html", fees=fees)


@bp.route("/api/extra-fees", methods=["POST"])
def add_extra_fee():
    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400
    statuses = (data.get("statuses") or "").strip()
    total_amount = data.get("total_amount")
    deadline = (data.get("deadline") or "").strip() or None
    if total_amount is not None:
        try:
            total_amount = float(total_amount)
            if total_amount <= 0:
                raise ValueError
        except (TypeError, ValueError):
            return jsonify({"error": "total_amount must be a positive number"}), 400
    with _get_repo() as repo:
        try:
            fid = repo.add_extra_fee(name, statuses, total_amount, deadline)
        except Exception:
            return jsonify({"error": "Fee tracker name already exists"}), 409
    return jsonify({"ok": True, "id": fid})


@bp.route("/api/extra-fees/<int:fee_id>", methods=["PUT"])
def update_extra_fee(fee_id: int):
    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400
    name = data.get("name")
    statuses = data.get("statuses")
    total_amount = data.get("total_amount", False)
    deadline = data.get("deadline", False)
    if name is not None:
        name = name.strip()
        if not name:
            return jsonify({"error": "name cannot be empty"}), 400
    if statuses is not None:
        statuses = statuses.strip()
    if total_amount is not False and total_amount is not None:
        try:
            total_amount = float(total_amount)
            if total_amount <= 0:
                raise ValueError
        except (TypeError, ValueError):
            return jsonify({"error": "total_amount must be a positive number"}), 400
    if deadline is not False:
        deadline = (deadline or "").strip() or None
    with _get_repo() as repo:
        ok = repo.update_extra_fee(fee_id, name=name, statuses=statuses,
                                   total_amount=total_amount, deadline=deadline)
    if not ok:
        return jsonify({"error": "Fee tracker not found"}), 404
    return jsonify({"ok": True})


@bp.route("/api/extra-fees/<int:fee_id>", methods=["DELETE"])
def delete_extra_fee(fee_id: int):
    with _get_repo() as repo:
        ok = repo.delete_extra_fee(fee_id)
    if not ok:
        return jsonify({"error": "Fee tracker not found"}), 404
    return jsonify({"ok": True})


@bp.route("/api/extra-fees/<int:fee_id>/entries", methods=["POST"])
def add_fee_entry(fee_id: int):
    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400
    entry_date = (data.get("date") or "").strip()
    amount = data.get("amount")
    name = (data.get("name") or "").strip()
    note = (data.get("note") or "").strip()
    status = (data.get("status") or "").strip()
    if not entry_date:
        return jsonify({"error": "date is required"}), 400
    if not name:
        return jsonify({"error": "name is required"}), 400
    try:
        amount = float(amount)
        if amount <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({"error": "amount must be a positive number"}), 400
    with _get_repo() as repo:
        fee = repo.get_extra_fee(fee_id)
        if not fee:
            return jsonify({"error": "Fee tracker not found"}), 404
        if fee["statuses_list"] and status not in fee["statuses_list"]:
            return jsonify({"error": f"Invalid status. Must be one of: {', '.join(fee['statuses_list'])}"}), 400
        eid = repo.add_extra_fee_entry(fee_id, entry_date, amount, name, note, status)
    return jsonify({"ok": True, "id": eid})


@bp.route("/api/extra-fees/<int:fee_id>/entries/<int:entry_id>", methods=["PUT"])
def update_fee_entry(fee_id: int, entry_id: int):
    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400
    entry_date = data.get("date")
    amount = data.get("amount")
    name = data.get("name")
    note = data.get("note")
    status = data.get("status")
    if amount is not None:
        try:
            amount = float(amount)
            if amount <= 0:
                raise ValueError
        except (TypeError, ValueError):
            return jsonify({"error": "amount must be a positive number"}), 400
    with _get_repo() as repo:
        if status is not None:
            fee = repo.get_extra_fee(fee_id)
            if not fee:
                return jsonify({"error": "Fee tracker not found"}), 404
            if fee["statuses_list"] and status.strip() not in fee["statuses_list"]:
                return jsonify({"error": f"Invalid status. Must be one of: {', '.join(fee['statuses_list'])}"}), 400
        ok = repo.update_extra_fee_entry(entry_id, date=entry_date, amount=amount,
                                         name=name, note=note, status=status)
    if not ok:
        return jsonify({"error": "Entry not found"}), 404
    return jsonify({"ok": True})


@bp.route("/api/extra-fees/<int:fee_id>/entries/<int:entry_id>", methods=["DELETE"])
def delete_fee_entry(fee_id: int, entry_id: int):
    with _get_repo() as repo:
        ok = repo.delete_extra_fee_entry(entry_id)
    if not ok:
        return jsonify({"error": "Entry not found"}), 404
    return jsonify({"ok": True})


# ── Investments ──

@bp.route("/investments")
def investments():
    import json
    with _get_repo() as repo:
        invs = repo.get_investments()
        for inv in invs:
            inv["entries"] = repo.get_investment_items(inv["id"])
        raw = repo.get_setting("unit_converters")
    converters = json.loads(raw) if raw else {}
    return render_template("investments.html", investments=invs, converters=converters)


@bp.route("/api/investments", methods=["POST"])
def add_investment():
    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400
    description = (data.get("description") or "").strip()
    unit = (data.get("unit") or "VND").strip()
    with _get_repo() as repo:
        try:
            iid = repo.add_investment(name, description, unit)
        except Exception:
            return jsonify({"error": "Investment name already exists"}), 409
    return jsonify({"ok": True, "id": iid})


@bp.route("/api/investments/<int:investment_id>", methods=["PUT"])
def update_investment(investment_id: int):
    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400
    name = data.get("name")
    description = data.get("description")
    unit = data.get("unit")
    if name is not None:
        name = name.strip()
        if not name:
            return jsonify({"error": "name cannot be empty"}), 400
    with _get_repo() as repo:
        ok = repo.update_investment(investment_id, name=name, description=description, unit=unit)
    if not ok:
        return jsonify({"error": "Investment not found"}), 404
    return jsonify({"ok": True})


@bp.route("/api/investments/<int:investment_id>", methods=["DELETE"])
def delete_investment(investment_id: int):
    with _get_repo() as repo:
        ok = repo.delete_investment(investment_id)
    if not ok:
        return jsonify({"error": "Investment not found"}), 404
    return jsonify({"ok": True})


@bp.route("/api/investments/<int:investment_id>/items", methods=["POST"])
def add_investment_item(investment_id: int):
    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400
    item_date = (data.get("date") or "").strip()
    amount = data.get("amount")
    note = (data.get("note") or "").strip()
    if not item_date:
        return jsonify({"error": "date is required"}), 400
    try:
        amount = float(amount)
        if amount <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({"error": "amount must be a positive number"}), 400
    with _get_repo() as repo:
        if not repo.get_investment(investment_id):
            return jsonify({"error": "Investment not found"}), 404
        iid = repo.add_investment_item(investment_id, item_date, amount, note)
    return jsonify({"ok": True, "id": iid})


@bp.route("/api/investments/<int:investment_id>/items/<int:item_id>", methods=["PUT"])
def update_investment_item(investment_id: int, item_id: int):
    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400
    item_date = data.get("date")
    amount = data.get("amount")
    note = data.get("note")
    if amount is not None:
        try:
            amount = float(amount)
            if amount <= 0:
                raise ValueError
        except (TypeError, ValueError):
            return jsonify({"error": "amount must be a positive number"}), 400
    with _get_repo() as repo:
        ok = repo.update_investment_item(item_id, date=item_date, amount=amount, note=note)
    if not ok:
        return jsonify({"error": "Item not found"}), 404
    return jsonify({"ok": True})


@bp.route("/api/investments/<int:investment_id>/items/<int:item_id>", methods=["DELETE"])
def delete_investment_item(investment_id: int, item_id: int):
    with _get_repo() as repo:
        ok = repo.delete_investment_item(item_id)
    if not ok:
        return jsonify({"error": "Item not found"}), 404
    return jsonify({"ok": True})


# ── Pays ──

@bp.route("/pays")
def pays():
    with _get_repo() as repo:
        pays_list = repo.get_pays()
    return render_template("pays.html", pays=pays_list)


@bp.route("/api/pays", methods=["POST"])
def add_pay():
    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400
    description = (data.get("description") or "").strip()
    with _get_repo() as repo:
        try:
            pid = repo.add_pay(name, description)
        except Exception:
            return jsonify({"error": "Pay name already exists"}), 409
    return jsonify({"ok": True, "id": pid})


@bp.route("/api/pays/<int:pay_id>", methods=["PUT"])
def update_pay(pay_id: int):
    data = request.get_json()
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400
    description = (data.get("description") or "").strip()
    with _get_repo() as repo:
        ok = repo.update_pay(pay_id, name, description)
    if not ok:
        return jsonify({"error": "Not found"}), 404
    return jsonify({"ok": True})


@bp.route("/api/pays/<int:pay_id>", methods=["DELETE"])
def delete_pay(pay_id: int):
    with _get_repo() as repo:
        ok = repo.delete_pay(pay_id)
    if not ok:
        return jsonify({"error": "Not found"}), 404
    return jsonify({"ok": True})


@bp.route("/api/pays/<int:pay_id>/items", methods=["POST"])
def add_pay_item(pay_id: int):
    data = request.get_json()
    date_val = (data.get("date") or "").strip()
    amount = data.get("amount")
    if not date_val:
        return jsonify({"error": "date is required"}), 400
    try:
        amount = float(amount)
        if amount <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({"error": "amount must be a positive number"}), 400
    note = (data.get("note") or "").strip()
    with _get_repo() as repo:
        iid = repo.add_pay_item(pay_id, date_val, amount, note)
    return jsonify({"ok": True, "id": iid})


@bp.route("/api/pays/<int:pay_id>/items/<int:item_id>", methods=["PUT"])
def update_pay_item(pay_id: int, item_id: int):
    data = request.get_json()
    date_val = (data.get("date") or "").strip()
    amount = data.get("amount")
    if not date_val:
        return jsonify({"error": "date is required"}), 400
    try:
        amount = float(amount)
        if amount <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({"error": "amount must be a positive number"}), 400
    note = (data.get("note") or "").strip()
    with _get_repo() as repo:
        ok = repo.update_pay_item(item_id, date_val, amount, note)
    if not ok:
        return jsonify({"error": "Not found"}), 404
    return jsonify({"ok": True})


@bp.route("/api/pays/<int:pay_id>/items/<int:item_id>/paid", methods=["POST"])
def toggle_pay_item_paid(pay_id: int, item_id: int):
    data = request.get_json()
    paid = bool(data.get("paid", True))
    with _get_repo() as repo:
        ok = repo.mark_pay_item_paid(item_id, paid)
    if not ok:
        return jsonify({"error": "Not found"}), 404
    return jsonify({"ok": True})


@bp.route("/api/pays/<int:pay_id>/items/<int:item_id>", methods=["DELETE"])
def delete_pay_item(pay_id: int, item_id: int):
    with _get_repo() as repo:
        ok = repo.delete_pay_item(item_id)
    if not ok:
        return jsonify({"error": "Not found"}), 404
    return jsonify({"ok": True})


# ── Assets ──

@bp.route("/assets")
def assets():
    import json
    with _get_repo() as repo:
        assets_list = repo.get_assets()
        raw = repo.get_setting("unit_converters")
    converters = json.loads(raw) if raw else {}
    return render_template("assets.html", assets=assets_list, converters=converters)


@bp.route("/api/assets", methods=["POST"])
def add_asset():
    data = request.get_json()
    if not data:
        return jsonify({"error": "JSON body required"}), 400
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400
    try:
        amount = float(data.get("amount", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "amount must be a number"}), 400
    description = (data.get("description") or "").strip()
    unit = (data.get("unit") or "VND").strip()
    with _get_repo() as repo:
        try:
            aid = repo.add_asset(name, description, amount, unit)
        except Exception:
            return jsonify({"error": "Asset name already exists"}), 409
    return jsonify({"ok": True, "id": aid})


@bp.route("/api/assets/<int:asset_id>", methods=["PUT"])
def update_asset(asset_id: int):
    data = request.get_json()
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400
    try:
        amount = float(data.get("amount", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "amount must be a number"}), 400
    description = (data.get("description") or "").strip()
    unit = (data.get("unit") or "VND").strip()
    with _get_repo() as repo:
        ok = repo.update_asset(asset_id, name, description, amount, unit)
    if not ok:
        return jsonify({"error": "Not found"}), 404
    return jsonify({"ok": True})


@bp.route("/api/assets/<int:asset_id>", methods=["DELETE"])
def delete_asset(asset_id: int):
    with _get_repo() as repo:
        ok = repo.delete_asset(asset_id)
    if not ok:
        return jsonify({"error": "Not found"}), 404
    return jsonify({"ok": True})


# ── Portfolios ──

@bp.route("/portfolios")
def portfolios():
    import json
    with _get_repo() as repo:
        assets_list = repo.get_assets()
        investments_list = repo.get_investments()
        savings_list = repo.get_savings()
        pays_list = repo.get_pays()
        raw = repo.get_setting("unit_converters")
    converters = json.loads(raw) if raw else {}
    return render_template(
        "portfolios.html",
        assets=assets_list,
        investments=investments_list,
        savings=savings_list,
        pays=pays_list,
        converters=converters,
    )
