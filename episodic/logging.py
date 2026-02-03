"""Logging helpers for femtologging integration."""

from __future__ import annotations

import enum
import typing as typ

from femtologging import basicConfig, get_logger


class LogLevel(enum.StrEnum):
    """Supported log levels for femtologging."""

    TRACE = "TRACE"
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARN = "WARN"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


def configure_logging(level: str | None, *, force: bool = False) -> tuple[str, bool]:
    """Configure femtologging and return the normalised level."""
    if not level:
        basicConfig(level="INFO", force=force)
        return ("INFO", True)

    normalised = level.strip().upper()
    if normalised not in LogLevel.__members__:
        basicConfig(level="INFO", force=force)
        return ("INFO", True)

    basicConfig(level=normalised, force=force)
    return (normalised, False)


class _SupportsLog(typ.Protocol):
    def log(
        self,
        level: str,
        message: str,
        /,
        *,
        exc_info: object | None = None,
        stack_info: bool = False,
    ) -> str | None: ...


def _log(
    logger: _SupportsLog,
    level: str,
    template: str,
    *args: object,
    exc_info: object | None = None,
) -> None:
    message = template % args if args else template
    logger.log(
        level,
        message,
        exc_info=exc_info,
        stack_info=False,
    )


def log_info(
    logger: _SupportsLog,
    template: str,
    *args: object,
    exc_info: object | None = None,
) -> None:
    """Log an INFO message with percent-style formatting."""
    _log(logger, "INFO", template, *args, exc_info=exc_info)


def log_warning(
    logger: _SupportsLog,
    template: str,
    *args: object,
    exc_info: object | None = None,
) -> None:
    """Log a WARNING message with percent-style formatting."""
    _log(logger, "WARNING", template, *args, exc_info=exc_info)


def log_error(
    logger: _SupportsLog,
    template: str,
    *args: object,
    exc_info: object | None = None,
) -> None:
    """Log an ERROR message with percent-style formatting."""
    _log(logger, "ERROR", template, *args, exc_info=exc_info)


__all__ = [
    "LogLevel",
    "configure_logging",
    "get_logger",
    "log_error",
    "log_info",
    "log_warning",
]
