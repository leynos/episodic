"""Logging helpers for femtologging integration."""

from __future__ import annotations

import enum
import typing as typ

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
    """Log an INFO message with percent-style formatting.

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
    _log(logger, "INFO", template, *args, exc_info=exc_info)


def log_warning(
    logger: _SupportsLog,
    template: str,
    *args: object,
    exc_info: object | None = None,
) -> None:
    """Log a WARNING message with percent-style formatting.

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
    _log(logger, "WARNING", template, *args, exc_info=exc_info)


def log_error(
    logger: _SupportsLog,
    template: str,
    *args: object,
    exc_info: object | None = None,
) -> None:
    """Log an ERROR message with percent-style formatting.

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
    _log(logger, "ERROR", template, *args, exc_info=exc_info)


__all__ = [
    "LogLevel",
    "configure_logging",
    "get_logger",
    "log_error",
    "log_info",
    "log_warning",
]
