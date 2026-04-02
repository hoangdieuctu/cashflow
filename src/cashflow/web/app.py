"""Flask application factory."""

from __future__ import annotations

from pathlib import Path

from flask import Flask

from cashflow.config import DATABASE_PATH


def create_app(db_path: str | None = None) -> Flask:
    """Create and configure the Flask application."""
    app = Flask(
        __name__,
        template_folder=str(Path(__file__).parent / "templates"),
        static_folder=str(Path(__file__).parent / "static"),
    )

    app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50 MB
    app.config["DB_PATH"] = db_path or str(DATABASE_PATH)
    app.secret_key = "cashflow-dev-key"

    from cashflow.web.routes import bp
    app.register_blueprint(bp)

    _start_backup_scheduler(app)

    from datetime import datetime, timezone

    @app.before_request
    def require_passcode():
        from flask import request, session, redirect, url_for
        from cashflow.database.repository import Repository
        if request.endpoint in ("main.lock", "main.lock_now", "static"):
            return
        with Repository(app.config["DB_PATH"]) as repo:
            enabled = repo.get_setting("passcode_enabled") == "1"
        if not enabled:
            return
        auth_at = session.get("authenticated_at")
        if auth_at and (datetime.now(timezone.utc).timestamp() - auth_at) < 300:
            session["authenticated_at"] = datetime.now(timezone.utc).timestamp()
            return
        session.pop("authenticated_at", None)
        return redirect(url_for("main.lock", next=request.path))

    @app.context_processor
    def inject_globals():
        """Inject global template variables."""
        import calendar
        from datetime import date
        from cashflow.database.db import get_connection
        result = {}

        # Passcode enabled flag
        try:
            from cashflow.database.repository import Repository
            with Repository(app.config["DB_PATH"]) as repo:
                result["passcode_enabled"] = repo.get_setting("passcode_enabled") == "1"
        except Exception:
            result["passcode_enabled"] = False

        # Savings maturing this month
        try:
            today = date.today()
            current_ym = today.strftime("%Y-%m")
            conn = get_connection(app.config["DB_PATH"])
            rows = conn.execute(
                "SELECT start_date, term_months FROM savings"
            ).fetchall()
            conn.close()
            count = 0
            for r in rows:
                try:
                    start = date.fromisoformat(r["start_date"])
                    yr = start.year + (start.month - 1 + r["term_months"]) // 12
                    mo = (start.month - 1 + r["term_months"]) % 12 + 1
                    dy = min(start.day, calendar.monthrange(yr, mo)[1])
                    maturity = date(yr, mo, dy)
                    if maturity.strftime("%Y-%m") == current_ym and maturity >= today:
                        count += 1
                except (ValueError, TypeError):
                    pass
            result["savings_maturing_this_month"] = count
        except Exception:
            result["savings_maturing_this_month"] = 0

        # Extra fees nearing deadline (within 31 days)
        try:
            today = date.today()
            conn = get_connection(app.config["DB_PATH"])
            rows = conn.execute(
                "SELECT deadline FROM extra_fees WHERE deadline IS NOT NULL AND deadline != ''"
            ).fetchall()
            conn.close()
            warn_count = 0
            for r in rows:
                try:
                    dl = date.fromisoformat(r["deadline"])
                    if (dl - today).days <= 31:
                        warn_count += 1
                except (ValueError, TypeError):
                    pass
            result["extra_fees_warning_count"] = warn_count
        except Exception:
            result["extra_fees_warning_count"] = 0

        # Pays with unpaid items due within 7 days (including overdue)
        try:
            today = date.today()
            conn = get_connection(app.config["DB_PATH"])
            rows = conn.execute(
                "SELECT date FROM pay_items WHERE paid = 0 AND date IS NOT NULL AND date != ''"
            ).fetchall()
            conn.close()
            pays_warn = 0
            for r in rows:
                try:
                    dl = date.fromisoformat(r["date"])
                    if (dl - today).days <= 7:
                        pays_warn += 1
                except (ValueError, TypeError):
                    pass
            result["pays_warning_count"] = pays_warn
        except Exception:
            result["pays_warning_count"] = 0

        result["now_date"] = date.today().isoformat()
        return result

    @app.template_filter("strip_purchase_prefix")
    def strip_purchase_prefix_filter(value: str) -> str:
        import re
        if value:
            value = re.sub(r"^Giao dịch thanh toán/Purchase - (?:Số Thẻ/Card No: \S+\s*)?", "", value)
        return value

    @app.template_filter("todatetime")
    def todatetime_filter(value):
        from datetime import date
        if isinstance(value, date):
            return value
        try:
            return date.fromisoformat(value)
        except (TypeError, ValueError):
            return date.today()

    return app


def _start_backup_scheduler(app: Flask) -> None:
    """Start a background thread that sends a daily DB backup at the configured time."""
    import threading
    import time

    def _run():
        last_sent_date = None
        while True:
            time.sleep(30)
            try:
                from cashflow.database.repository import Repository
                with Repository(app.config["DB_PATH"]) as repo:
                    enabled = repo.get_setting("backup_schedule_enabled") == "1"
                    hour = int(repo.get_setting("backup_schedule_hour") or 8)
                    minute = int(repo.get_setting("backup_schedule_minute") or 0)
                if not enabled:
                    continue
                from datetime import datetime
                now = datetime.now()
                today = now.date()
                if now.hour == hour and now.minute == minute and last_sent_date != today:
                    with app.app_context():
                        _send_backup_email(app)
                    last_sent_date = today
            except Exception:
                pass

    t = threading.Thread(target=_run, daemon=True)
    t.start()


def _send_backup_email(app: Flask) -> None:
    """Send backup email — shared logic used by scheduler and API route."""
    import shutil
    import smtplib
    import tempfile
    import os
    from datetime import date
    from email import encoders
    from email.mime.base import MIMEBase
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText

    from cashflow import __version__

    with app.app_context():
        from cashflow.database.repository import Repository
        with Repository(app.config["DB_PATH"]) as repo:
            smtp_host = repo.get_setting("backup_smtp_host")
            smtp_port = int(repo.get_setting("backup_smtp_port") or 465)
            smtp_user = repo.get_setting("backup_smtp_user")
            smtp_pass = repo.get_setting("backup_smtp_pass")
            recipient = repo.get_setting("backup_recipient")

    if not smtp_host or not smtp_user or not recipient:
        raise ValueError("Email backup is not configured")

    filename = f"cashflow-{__version__}-{date.today().strftime('%Y%m%d')}.db"
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            tmp_path = tmp.name
        shutil.copy2(app.config["DB_PATH"], tmp_path)

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
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
