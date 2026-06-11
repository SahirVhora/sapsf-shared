"""Logging setup shared across SAP SuccessFactors tools.

Provides a consistent, pretty log format (coloured in the console, plain in files)
with sensible defaults. Tools call setup_logging() once at startup.
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from rich.logging import RichHandler


class ColoredFormatter(logging.Formatter):
    """Simple colourised formatter for console output (no Rich dependency)."""

    _COLORS = {
        "DEBUG": "\033[36m",      # cyan
        "INFO": "\033[32m",       # green
        "WARNING": "\033[33m",    # yellow
        "ERROR": "\033[31m",      # red
        "CRITICAL": "\033[35m",   # magenta
    }
    _RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self._COLORS.get(record.levelname, "")
        record.levelname = f"{color}{record.levelname}{self._RESET}"
        return super().format(record)


def setup_logging(
    level: int | str = logging.INFO,
    *,
    log_dir: Path | str | None = None,
    log_file: str | None = None,
    max_bytes: int = 5_000_000,
    backup_count: int = 3,
    rich_console: bool = True,
    format_str: str | None = None,
) -> None:
    """Configure root logging for an SAP SF tool.

    Args:
        level: Log level (e.g. logging.DEBUG or "DEBUG")
        log_dir: Directory for rotating file logs. If None, no file handler.
        log_file: Filename inside log_dir. Defaults to "app.log"
        max_bytes: Max size per log file before rotation
        backup_count: Number of backup files to keep
        rich_console: Use RichHandler (pretty) instead of plain StreamHandler
        format_str: Override the default log format string
    """
    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.INFO)

    fmt = format_str or "%(asctime)s %(levelname)s %(name)s: %(message)s"
    handlers: list[logging.Handler] = []

    # Console handler
    if rich_console:
        try:
            console_handler = RichHandler(
                show_time=True,
                show_path=False,
                rich_tracebacks=True,
            )
            console_handler.setFormatter(logging.Formatter(fmt))
        except Exception:
            # Fallback if Rich is not installed
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setFormatter(ColoredFormatter(fmt))
    else:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(ColoredFormatter(fmt))

    handlers.append(console_handler)

    # File handler
    if log_dir is not None:
        log_path = Path(log_dir)
        log_path.mkdir(parents=True, exist_ok=True)
        file_name = log_file or "app.log"
        file_handler = RotatingFileHandler(
            log_path / file_name,
            maxBytes=max_bytes,
            backupCount=backup_count,
        )
        file_handler.setFormatter(logging.Formatter(fmt))
        handlers.append(file_handler)

    logging.basicConfig(
        level=level,
        handlers=handlers,
        force=True,  # override any existing basicConfig
    )
