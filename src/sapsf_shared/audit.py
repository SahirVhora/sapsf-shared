"""Audit logging for SAP SuccessFactors tools.

Provides a decorator and standalone logger for recording who did what,
when, and with what result. Audit events are written as JSON lines to a
rotating file log, suitable for SIEM ingestion or compliance reporting.

Usage:
    from sapsf_shared.audit import audit

    @audit("fetch_roles_permissions")
    def get_roles_permissions(self, role_ids: list[str]) -> dict:
        ...

    # Or manual:
    audit_log("sf-audit", "compare", "success", duration_ms=1234.5)
"""

from __future__ import annotations

import json
import logging
import os as _os
import time
from collections.abc import Callable
from datetime import UTC, datetime
from functools import wraps
from pathlib import Path
from typing import Any

audit_logger = logging.getLogger("sapsf.audit")

# Default log path - can be overridden via SAPSF_AUDIT_LOG env var
_AUDIT_LOG_PATH = _os.environ.get(
    "SAPSF_AUDIT_LOG",
    str(Path.home() / ".local" / "share" / "sapsf" / "audit.jsonl"),
)


def _ensure_audit_log_dir() -> None:
    Path(_AUDIT_LOG_PATH).parent.mkdir(parents=True, exist_ok=True)


def audit_log(
    tool: str,
    action: str,
    status: str,
    *,
    duration_ms: float | None = None,
    details: str | None = None,
    tenant: str | None = None,
) -> None:
    """Write a structured audit event to the audit log.

    Args:
        tool: Name of the tool (e.g. 'sf-audit', 'sf-pic')
        action: What was performed (e.g. 'compare', 'scan', 'export')
        status: 'success' or 'error'
        duration_ms: Wall-clock duration in milliseconds
        details: Optional human-readable context
        tenant: Target SF tenant identifier (base_url or alias)
    """
    _ensure_audit_log_dir()
    event: dict[str, Any] = {
        "tool": tool,
        "action": action,
        "status": status,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    if duration_ms is not None:
        event["duration_ms"] = round(duration_ms, 1)
    if details:
        event["details"] = details[:1000]
    if tenant:
        event["tenant"] = tenant

    try:
        with open(_AUDIT_LOG_PATH, "a") as f:
            f.write(json.dumps(event) + "\n")
    except OSError:
        audit_logger.warning("Failed to write audit event (disk full or permission error)")
    audit_logger.debug("Audit: %s %s -> %s", tool, action, status)


def audit(action: str, *, tool: str = "sapsf-shared") -> Callable:
    """Decorator that logs an audit event on every invocation.

    On success: logs with status='success' and duration_ms.
    On failure: logs with status='error', error type, and message before re-raising.

    Args:
        action: Human-readable action name (e.g. 'fetch_roles')
        tool: Tool name for attribution (default: 'sapsf-shared')
    """

    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            start = time.monotonic()
            try:
                result = fn(*args, **kwargs)
                duration_ms = (time.monotonic() - start) * 1000
                audit_log(tool, action, "success", duration_ms=duration_ms)
                return result
            except Exception as exc:
                duration_ms = (time.monotonic() - start) * 1000
                audit_log(
                    tool,
                    action,
                    "error",
                    duration_ms=duration_ms,
                    details=f"{type(exc).__name__}: {str(exc)[:500]}",
                )
                raise

        return wrapper

    return decorator
