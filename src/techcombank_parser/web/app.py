"""Flask application factory."""

from __future__ import annotations

from pathlib import Path

from flask import Flask

from techcombank_parser.config import DATABASE_PATH


def create_app(db_path: str | None = None) -> Flask:
    """Create and configure the Flask application."""
    app = Flask(
        __name__,
        template_folder=str(Path(__file__).parent / "templates"),
        static_folder=str(Path(__file__).parent / "static"),
    )

    app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50 MB
    app.config["DB_PATH"] = db_path or str(DATABASE_PATH)
    app.secret_key = "techcombank-parser-dev-key"

    from techcombank_parser.web.routes import bp
    app.register_blueprint(bp)

    return app
