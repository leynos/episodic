"""Logging helpers for femtologging integration.

This module wraps femtologging with convenience helpers that keep logging
configuration and structured formatting consistent across the codebase.

Examples
--------
Configure logging and emit a message:

>>> level, used_default = configure_logging("INFO")
>>> log_info(get_logger(__name__), "Started %s", "ingestion")
"""

from __future__ import annotations

import enum
import typing as typ
import warnings

from femtologging import basicConfig, get_logger


class LogLevel(enum.StrEnum):
    """Supported log levels for femtologging.

    Attributes
    ----------
    TRACE : str
        Verbose trace-level logging.
    DEBUG : str
        Debug-level logging.
    INFO : str
        Informational logging.
    WARN : str
        Warning logging (deprecated alias of WARNING).
    WARNING : str
        Warning logging.
    ERROR : str
        Error logging.
    CRITICAL : str
        Critical error logging.
    """

    TRACE = "TRACE"
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARN = "WARN"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


def configure_logging(level: str | None, *, force: bool = False) -> tuple[str, bool]:
    """Configure femtologging and return the normalised level.

    Parameters
    ----------
    level : str | None
        Requested log level, or None to use the default.
    force : bool, optional
        Whether to force reconfiguration of logging handlers.

    Returns
    -------
    tuple[str, bool]
        A tuple of (effective_level, used_default), where used_default is True
        when the input was missing or invalid.
    """
    requested = level.strip().upper() if level else None
    if not requested or requested not in LogLevel.__members__:
        used_default = True
        normalised = LogLevel.INFO
    else:
        used_default = False
        normalised = LogLevel(requested)
        if normalised is LogLevel.WARN:
            warnings.warn(
                "LogLevel.WARN is deprecated; use LogLevel.WARNING instead.",
                DeprecationWarning,
                stacklevel=2,
            )
            normalised = LogLevel.WARNING

    basicConfig(level=normalised, force=force)
    return (normalised, used_default)


# _SupportsLog is private because callers can rely on structural typing instead.
class _SupportsLog(typ.Protocol):
    """Protocol for loggers supporting the femtologging API."""

    def log(
        self,
        level: str,
        message: str,
        /,
        *,
        exc_info: object | None = None,
        stack_info: bool = False,
    ) -> None: ...


def _format_message(template: str, args: tuple[object, ...]) -> str:
    """Format a log message template."""
    return template % args if args else template


def _emit(
    logger: _SupportsLog,
    level: LogLevel,
    message: str,
    exc_info: object | None = None,
) -> None:
    """Emit a log message."""
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
    """Format and emit an INFO log message.

    Parameters
    ----------
    logger : _SupportsLog
        Logger instance that supports the femtologging log API.
    template : str
        Percent-style format string for the log message.
    *args : object
        Arguments interpolated into the template.
    exc_info : object | None, optional
        Exception info to attach to the log record.

    Returns
    -------
    None

    Raises
    ------
    TypeError
        If the template and arguments do not align for percent formatting.
    """
    _emit(logger, LogLevel.INFO, _format_message(template, args), exc_info=exc_info)


def log_warning(
    logger: _SupportsLog,
    template: str,
    *args: object,
    exc_info: object | None = None,
) -> None:
    """Format and emit a WARNING log message.

    Parameters
    ----------
    logger : _SupportsLog
        Logger instance that supports the femtologging log API.
    template : str
        Percent-style format string for the log message.
    *args : object
        Arguments interpolated into the template.
    exc_info : object | None, optional
        Exception info to attach to the log record.

    Returns
    -------
    None

    Raises
    ------
    TypeError
        If the template and arguments do not align for percent formatting.
    """
    _emit(logger, LogLevel.WARNING, _format_message(template, args), exc_info=exc_info)


def log_error(
    logger: _SupportsLog,
    template: str,
    *args: object,
    exc_info: object | None = None,
) -> None:
    """Format and emit an ERROR log message.

    Parameters
    ----------
    logger : _SupportsLog
        Logger instance that supports the femtologging log API.
    template : str
        Percent-style format string for the log message.
    *args : object
        Arguments interpolated into the template.
    exc_info : object | None, optional
        Exception info to attach to the log record.

    Returns
    -------
    None

    Raises
    ------
    TypeError
        If the template and arguments do not align for percent formatting.
    """
    _emit(logger, LogLevel.ERROR, _format_message(template, args), exc_info=exc_info)


__all__ = (
    "LogLevel",
    "configure_logging",
    "get_logger",
    "log_error",
    "log_info",
    "log_warning",
)
