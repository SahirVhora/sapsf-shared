"""Flask base application helpers shared across SAP SF tools.

Provides a factory function that returns a pre-configured Flask app with:
  - Secret key (from env or auto-generated)
  - CSRF token generation and validation
  - Consistent logging setup
  - JSON error handlers
  - /api/health endpoint
  - CORS preflight support
  - Rotating file log handler
"""

from __future__ import annotations

import logging
import os
import secrets
from pathlib import Path
from typing import Any

from flask import Flask, abort, jsonify, request, session

logger = logging.getLogger(__name__)


class SFApp(Flask):
    """Pre-configured Flask app for SAP SF tools.

    Usage:
        app = create_app(__name__, secret_key="...", log_dir="logs")
        app.register_blueprint(my_bp)
        app.run(port=5050)
    """

    def __init__(
        self,
        import_name: str,
        *,
        template_folder: str | None = None,
        static_folder: str | None = None,
        secret_key: str | None = None,
        log_dir: Path | str | None = None,
        log_level: int | str = logging.INFO,
        enable_csrf: bool = True,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            import_name,
            template_folder=template_folder,
            static_folder=static_folder,
            **kwargs,
        )

        # Secret key
        self.secret_key = secret_key or os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32)

        # Logging
        if log_dir is not None:
            log_path = Path(log_dir)
            log_path.mkdir(parents=True, exist_ok=True)
            from logging.handlers import RotatingFileHandler

            if isinstance(log_level, str):
                log_level = getattr(logging, log_level.upper(), logging.INFO)
            fmt = "%(asctime)s %(levelname)s %(name)s: %(message)s"
            file_handler = RotatingFileHandler(
                log_path / "app.log",
                maxBytes=5_000_000,
                backupCount=3,
            )
            file_handler.setFormatter(logging.Formatter(fmt))
            file_handler.setLevel(log_level)
            self.logger.addHandler(file_handler)

        # CSRF
        self._enable_csrf = enable_csrf
        if enable_csrf:
            self.jinja_env.globals["csrf_token"] = self._get_csrf_token
            self.before_request(self._check_csrf)

        # Register built-in handlers
        self._register_health()
        self._register_error_handlers()
        self._register_cors()

    # ------------------------------------------------------------------
    # CSRF
    # ------------------------------------------------------------------

    def _get_csrf_token(self) -> str:
        if "csrf_token" not in session:
            session["csrf_token"] = secrets.token_urlsafe(32)
        return session["csrf_token"]  # type: ignore[no-any-return]

    def _check_csrf(self) -> None:
        if request.method == "POST":
            token = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
            if not token or token != session.get("csrf_token"):
                abort(403, "CSRF token missing or invalid")

    # ------------------------------------------------------------------
    # Health endpoint
    # ------------------------------------------------------------------

    def _register_health(self) -> None:
        @self.route("/api/health")
        def health() -> Any:
            return jsonify({
                "status": "ok",
                "service": self.name,
            })

    # ------------------------------------------------------------------
    # Error handlers
    # ------------------------------------------------------------------

    def _register_error_handlers(self) -> None:
        @self.errorhandler(400)
        def bad_request(exc: Exception) -> Any:
            return jsonify({"error": str(exc)}), 400

        @self.errorhandler(404)
        def not_found(exc: Exception) -> Any:
            return jsonify({"error": "Not found"}), 404

        @self.errorhandler(403)
        def forbidden(exc: Exception) -> Any:
            return jsonify({"error": str(exc)}), 403

        @self.errorhandler(500)
        def internal_error(exc: Exception) -> Any:
            logger.exception("Unhandled exception")
            return jsonify({"error": "Internal server error"}), 500

    # ------------------------------------------------------------------
    # CORS
    # ------------------------------------------------------------------

    def _register_cors(self) -> None:
        @self.after_request
        def add_cors_headers(response: Any) -> Any:
            origin = request.headers.get("Origin")
            if origin:
                response.headers["Access-Control-Allow-Origin"] = origin
                response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
                response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-CSRF-Token"
                response.headers["Access-Control-Allow-Credentials"] = "true"
            return response

        @self.before_request
        def handle_options() -> Any:
            if request.method == "OPTIONS":
                return "", 204
            return None


def create_app(
    import_name: str,
    *,
    secret_key: str | None = None,
    log_dir: Path | str | None = None,
    log_level: int | str = logging.INFO,
    enable_csrf: bool = True,
    **kwargs: Any,
) -> SFApp:
    """Factory function for creating a pre-configured SFApp.

    Args:
        import_name: Flask import name (usually __name__)
        secret_key: Flask secret key (falls back to FLASK_SECRET_KEY env var or auto-generated)
        log_dir: Directory for rotating file logs
        log_level: Logging level
        enable_csrf: Enable CSRF token validation on POST requests
        **kwargs: Passed to Flask constructor

    Returns:
        An SFApp instance ready for blueprint registration.
    """
    return SFApp(
        import_name,
        secret_key=secret_key,
        log_dir=log_dir,
        log_level=log_level,
        enable_csrf=enable_csrf,
        **kwargs,
    )
