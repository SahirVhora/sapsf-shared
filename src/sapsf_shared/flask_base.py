"""Flask base application helpers shared across SAP SF tools.

Provides a factory function that returns a pre-configured Flask app with:
  - Secret key (from env or auto-generated)
  - CSRF token generation and validation
  - Consistent logging setup
  - JSON error handlers
  - /api/health endpoint
  - CORS preflight support
  - Rotating file log handler
  - ``require_local_token`` decorator (ADR-0003) for header-only
    report-style endpoints. Never accept the token via the query string.
"""

from __future__ import annotations

import logging
import os
import secrets
from collections.abc import Callable
from functools import wraps
from pathlib import Path
from typing import Any

from flask import Flask, abort, current_app, jsonify, request, session

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
        cors_origins: list[str] | None = None,
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

        # CORS allowlist. Reflecting an arbitrary Origin with credentials lets
        # any site make credentialed cross-origin calls, so we only echo
        # Origins on an explicit allowlist. Source order: constructor arg,
        # then CORS_ALLOWED_ORIGINS env (comma-separated), else localhost only.
        if cors_origins is None:
            env_origins = os.environ.get("CORS_ALLOWED_ORIGINS", "")
            cors_origins = [o.strip() for o in env_origins.split(",") if o.strip()]
        if not cors_origins:
            cors_origins = [
                "http://localhost:5000",
                "http://127.0.0.1:5000",
            ]
        self._cors_origins = set(cors_origins)

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
            # JSON APIs: instead of skipping CSRF outright, require the request
            # to be application/json. A cross-site HTML form cannot send that
            # content type without a CORS preflight (blocked by our Origin
            # allowlist), so this stops classic form-based CSRF while keeping
            # the AJAX save+test flow working.
            if request.path.startswith("/api/"):
                ctype = (request.content_type or "").split(";")[0].strip().lower()
                if ctype != "application/json":
                    abort(415, "API requests must be application/json")
                return
            token = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
            if not token or not secrets.compare_digest(token, session.get("csrf_token", "")):
                abort(403, "CSRF token missing or invalid")

    # ------------------------------------------------------------------
    # Health endpoint
    # ------------------------------------------------------------------

    def _register_health(self) -> None:
        @self.route("/api/health")
        def health() -> Any:
            return jsonify(
                {
                    "status": "ok",
                    "service": self.name,
                }
            )

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

        @self.errorhandler(415)
        def unsupported_media_type(exc: Exception) -> Any:
            return jsonify({"error": str(exc)}), 415

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
            if origin and origin in self._cors_origins:
                response.headers["Access-Control-Allow-Origin"] = origin
                response.headers["Vary"] = "Origin"
                response.headers["Access-Control-Allow-Methods"] = (
                    "GET, POST, PUT, PATCH, DELETE, OPTIONS"
                )
                response.headers["Access-Control-Allow-Headers"] = (
                    "Content-Type, Authorization, X-CSRF-Token, X-Report-Token, X-Auth-Token"
                )
                response.headers["Access-Control-Allow-Credentials"] = "true"
            return response

        @self.before_request
        def handle_options() -> Any:
            if request.method == "OPTIONS":
                return "", 204
            return None


def require_local_token(
    token_supplier: Callable[[], str | None],
    *,
    header_name: str = "X-Report-Token",
) -> Callable:
    """Flask view decorator: header-only local-token gate (ADR-0003).

    Reads the token from the configured request header (``X-Report-Token`` by
    default). **Never** accepts the token via the query string. If ``?token=``
    is present we deliberately reject the request, so legacy clients fall over
    loudly instead of leaking through reverse-proxy / access-log / Referer
    headers.

    Args:
        token_supplier: A zero-arg callable returning the configured token
            (e.g. ``lambda: config.REPORT_ACCESS_TOKEN``). Returning ``None`` or
            an empty string makes the endpoint refuse every request (503) so a
            misconfigured deployment cannot become insecurely open.
        header_name: Request header name to read the supplied token from.
            Defaults to ``X-Report-Token``. Use ``X-Auth-Token`` for movement
            tools.

    The decorated view is rejected with 503 if the configured token is empty
    (operator never set it), 401 if a ``?token=`` query argument is present
    (legacy leak), and 403 if any other condition fails (no header, wrong
    header). All comparisons use ``secrets.compare_digest`` for constant-time
    safety.
    """

    def decorator(view: Callable) -> Callable:
        @wraps(view)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            configured = token_supplier() or ""
            if not configured:
                current_app.logger.warning(
                    "require_local_token rejected request: reason=not_configured path=%s remote=%s",
                    request.path,
                    request.remote_addr,
                )
                return (
                    jsonify(
                        {
                            "error": (
                                "Local auth token is not configured "
                                "for this deployment. Set REPORT_ACCESS_TOKEN "
                                "(or the tool-specific fallback) and restart."
                            )
                        }
                    ),
                    503,
                )
            # Deliberate rejection of ?token=... -- see ADR-0003 and R-001..R-004
            if "token" in request.args:
                current_app.logger.warning(
                    "require_local_token rejected request: reason=legacy_query "
                    "path=%s remote=%s (ADR-0003: header-only)",
                    request.path,
                    request.remote_addr,
                )
                return (
                    jsonify(
                        {
                            "error": (
                                "Auth tokens must be sent as the "
                                f"{header_name} header. The ?token= query "
                                "parameter is no longer accepted."
                            )
                        }
                    ),
                    401,
                )
            supplied = request.headers.get(header_name, "")
            if not supplied or not secrets.compare_digest(
                supplied.encode("utf-8"), configured.encode("utf-8")
            ):
                current_app.logger.warning(
                    "require_local_token rejected request: reason=missing_or_invalid_header "
                    "header=%s path=%s remote=%s",
                    header_name,
                    request.path,
                    request.remote_addr,
                )
                return (
                    jsonify(
                        {
                            "error": (
                                f"Missing or invalid auth token. Pass it in the "
                                f"{header_name} header."
                            )
                        }
                    ),
                    403,
                )
            return view(*args, **kwargs)

        return wrapper

    return decorator


def check_local_token(
    configured: str | None,
    *,
    header_name: str = "X-Report-Token",
    legacy_query_arg: str = "token",
) -> bool:
    """Minimum-disruption local-token check used by existing report routes.

    This helper exists so the four ADR-0003 sites (sf-config-compare,
    sf-config-compare-ec, sf-metadata-vault, sf-object-sync) can adopt
    header-first auth **without** breaking the existing flow while owners
    transition clients. Behaviour:

    1. ``configured`` empty / falsy → return ``True`` (no token required for
       this deployment, matches the existing inline guards).
    2. Header ``header_name`` provided and matches → ``True``.
    3. Otherwise fall back to legacy ``?{legacy_query_arg}=`` (with warning
       log so it is visible in monitoring).
    4. Returns ``False`` if neither matches; the caller aborts 403.

    The legacy query-string fallback is **deprecated**; new code should use
    :func:`require_local_token` instead. We keep this helper as the bridge
    because it keeps the existing ``_check_report_token`` call sites working
    until query-string-using clients (links in older reports) are updated.

    Args:
        configured: The configured token (e.g. ``REPORT_ACCESS_TOKEN``).
        header_name: Request header to read first. Default ``X-Report-Token``.
        legacy_query_arg: Query-string parameter name accepted as fallback.

    Returns:
        ``True`` if the request is authorised, ``False`` otherwise.
    """
    if not configured:
        return True
    supplied = request.headers.get(header_name, "")
    if supplied and secrets.compare_digest(supplied.encode("utf-8"), configured.encode("utf-8")):
        return True
    legacy = request.args.get(legacy_query_arg, "")
    if legacy and secrets.compare_digest(legacy.encode("utf-8"), configured.encode("utf-8")):
        current_app.logger.warning(
            "check_local_token accepted deprecated query token: path=%s remote=%s "
            "query_arg=%s (switch to %s header per ADR-0003)",
            request.path,
            request.remote_addr,
            legacy_query_arg,
            header_name,
        )
        return True
    current_app.logger.warning(
        "check_local_token rejected request: reason=missing_or_invalid_token path=%s remote=%s",
        request.path,
        request.remote_addr,
    )
    return False


def create_app(
    import_name: str,
    *,
    secret_key: str | None = None,
    log_dir: Path | str | None = None,
    log_level: int | str = logging.INFO,
    enable_csrf: bool = True,
    cors_origins: list[str] | None = None,
    **kwargs: Any,
) -> SFApp:
    """Factory function for creating a pre-configured SFApp.

    Args:
        import_name: Flask import name (usually __name__)
        secret_key: Flask secret key (falls back to FLASK_SECRET_KEY env var or auto-generated)
        log_dir: Directory for rotating file logs
        log_level: Logging level
        enable_csrf: Enable CSRF token validation on POST requests
        cors_origins: Explicit CORS allowlist. Defaults to localhost only.
            Override via CORS_ALLOWED_ORIGINS env (comma-separated).
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
        cors_origins=cors_origins,
        **kwargs,
    )
