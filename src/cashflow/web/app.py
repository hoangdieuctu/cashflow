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

        return result

    return app
