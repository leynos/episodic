"""Logging helpers for femtologging integration.

This module owns the application's logging port over femtologging.

Examples
--------
Configure logging and emit a message:

>>> level, used_default = configure_logging("INFO")
>>> logger = get_logger(__name__)
>>> log_info(logger, "Started ingestion")
"""

import enum
import logging
import typing as typ
import warnings

from femtologging import basicConfig
from femtologging import get_logger as _get_femtologger


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


def configure_logging(
    level: str | None, *, force: bool = False
) -> tuple[LogLevel, bool]:
    """Configure femtologging and return the normalized level.

    Parameters
    ----------
    level : str | None
        Requested log level, or None to use the default.
    force : bool, optional
        Whether to force reconfiguration of logging handlers.

    Returns
    -------
    tuple[LogLevel, bool]
        A tuple of (effective_level, used_default), where used_default is True
        when the input was missing or invalid.
    """
    requested = level.strip().upper() if level else None
    if not requested or requested not in LogLevel.__members__:
        used_default = True
        normalized = LogLevel.INFO
    else:
        used_default = False
        normalized = LogLevel(requested)
        if normalized is LogLevel.WARN:
            warnings.warn(
                "LogLevel.WARN is deprecated; use LogLevel.WARNING instead.",
                DeprecationWarning,
                stacklevel=2,
            )
            normalized = LogLevel.WARNING

    basicConfig(level=normalized, force=force)
    return (normalized, used_default)


# _SupportsLog is private because callers can rely on structural typing instead.
class _SupportsConvenienceLog(typ.Protocol):
    """Protocol for loggers supporting stdlib-like femtologging methods."""

    def debug(
        self,
        message: str,
        /,
        *,
        exc_info: object | None = None,
        stack_info: bool = False,
    ) -> None:
        """Emit a DEBUG-level log record."""

    def info(
        self,
        message: str,
        /,
        *,
        exc_info: object | None = None,
        stack_info: bool = False,
    ) -> None:
        """Emit an INFO-level log record."""

    def warning(
        self,
        message: str,
        /,
        *,
        exc_info: object | None = None,
        stack_info: bool = False,
    ) -> None:
        """Emit a WARNING-level log record."""

    def error(
        self,
        message: str,
        /,
        *,
        exc_info: object | None = None,
        stack_info: bool = False,
    ) -> None:
        """Emit an ERROR-level log record."""

    def exception(
        self,
        message: str,
        /,
        *,
        exc_info: object | None = None,
        stack_info: bool = False,
    ) -> None:
        """Emit an ERROR-level record with exception information."""


class _SupportsLogMethod(typ.Protocol):
    """Protocol for loggers exposing the stdlib-style `log` entry point."""

    def log(
        self,
        level: int | LogLevel,
        message: str,
        /,
        *,
        exc_info: object | None = None,
        stack_info: bool = False,
    ) -> None:
        """Emit a log record at the given numeric or LogLevel level."""


type _CompatibleLogger = _SupportsConvenienceLog | _SupportsLogMethod
type _ConvenienceMethod = typ.Literal[
    "debug",
    "info",
    "warning",
    "error",
    "exception",
]
type _LogCall = tuple[int, _ConvenienceMethod]


class LoggerHandle:
    """Opaque handle accepted by the Episodic logging port.

    Callers obtain a handle from :func:`get_logger` and emit records through
    ``log_debug``, ``log_info``, ``log_warning``, ``log_error``, or
    ``log_exception``. The private backend remains inaccessible so future
    cross-cutting context is attached consistently at this port.
    """

    def __init__(self, logger: _CompatibleLogger) -> None:
        """Wrap a compatible backend logger for use by port helpers."""
        self._logger = logger


def get_logger(name: str) -> LoggerHandle:
    """Return an opaque logging-port handle for *name*."""
    return LoggerHandle(typ.cast("_CompatibleLogger", _get_femtologger(name)))


getLogger = get_logger  # noqa: N816  # Preserve the stdlib-compatible constructor alias.


def _format_message(template: str, args: tuple[object, ...]) -> str:
    """Format a log message template."""
    return template % args if args else template


def _emit(
    logger: LoggerHandle,
    log_call: _LogCall,
    message: str,
    exc_info: object | None,
) -> None:
    """Dispatch one pre-formatted message through the wrapped backend."""
    level, convenience_method = log_call
    backend = logger._logger
    try:
        method = getattr(
            typ.cast("_SupportsConvenienceLog", backend), convenience_method
        )
        method(message, exc_info=exc_info, stack_info=False)
    except (AttributeError, TypeError):  # fmt: skip
        typ.cast("_SupportsLogMethod", backend).log(
            level,
            message,
            exc_info=exc_info,
            stack_info=False,
        )


def log_debug(
    logger: LoggerHandle,
    template: str,
    *args: object,
    exc_info: object | None = None,
) -> None:
    """Format and emit a DEBUG log message through the port."""
    _emit(
        logger,
        (logging.DEBUG, "debug"),
        _format_message(template, args),
        exc_info,
    )


def log_info(
    logger: LoggerHandle,
    template: str,
    *args: object,
    exc_info: object | None = None,
) -> None:
    """Format and emit an INFO log message.

    Parameters
    ----------
    logger : LoggerHandle
        Opaque handle returned by :func:`get_logger`.
    template : str
        Percent-style format string for the log message.
    *args : object
        Arguments interpolated into the template.
    exc_info : object | None, optional
        Exception info to attach to the log record.
    """
    _emit(
        logger,
        (logging.INFO, "info"),
        _format_message(template, args),
        exc_info,
    )


def log_warning(
    logger: LoggerHandle,
    template: str,
    *args: object,
    exc_info: object | None = None,
) -> None:
    """Format and emit a WARNING log message.

    Parameters
    ----------
    logger : LoggerHandle
        Opaque handle returned by :func:`get_logger`.
    template : str
        Percent-style format string for the log message.
    *args : object
        Arguments interpolated into the template.
    exc_info : object | None, optional
        Exception info to attach to the log record.
    """
    _emit(
        logger,
        (logging.WARNING, "warning"),
        _format_message(template, args),
        exc_info,
    )


def log_error(
    logger: LoggerHandle,
    template: str,
    *args: object,
    exc_info: object | None = None,
) -> None:
    """Format and emit an ERROR log message.

    Parameters
    ----------
    logger : LoggerHandle
        Opaque handle returned by :func:`get_logger`.
    template : str
        Percent-style format string for the log message.
    *args : object
        Arguments interpolated into the template.
    exc_info : object | None, optional
        Exception info to attach to the log record.
    """
    _emit(
        logger,
        (logging.ERROR, "error"),
        _format_message(template, args),
        exc_info,
    )


def log_exception(
    logger: LoggerHandle,
    template: str,
    *args: object,
    exc_info: object | None = True,
) -> None:
    """Format and emit an exception record with traceback information."""
    _emit(
        logger,
        (logging.ERROR, "exception"),
        _format_message(template, args),
        exc_info,
    )


__all__ = (
    "LogLevel",
    "LoggerHandle",
    "configure_logging",
    "getLogger",
    "get_logger",
    "log_debug",
    "log_error",
    "log_exception",
    "log_info",
    "log_warning",
)
