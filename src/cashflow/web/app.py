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

    @app.context_processor
    def inject_savings_badge():
        """Inject count of savings maturing in the current month into all templates."""
        import calendar
        from datetime import date
        from cashflow.database.db import get_connection
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
        except Exception:
            count = 0
        return {"savings_maturing_this_month": count}

    return app
