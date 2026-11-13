"""Logging helpers for femtologging integration.

This module owns the application's logging port over femtologging.

Examples
--------
Configure logging and emit a message:

>>> level, used_default = configure_logging("INFO")
>>> logger = get_logger(__name__)
>>> log_info(logger, "Started ingestion")
"""

import datetime as dt
import enum
import json
import logging
import typing as typ
import warnings

from femtologging import basicConfig
from femtologging import get_logger as _get_femtologger

from episodic._logging_types import (
    _LogCall,
    _LogWrapperConfig,
    _method_rejects_logging_call,
    _SupportsConvenienceLog,
)


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


class _LogWrapper(typ.Protocol):
    """Callable surface shared by the level-specific logging wrappers."""

    def __call__(
        self,
        logger: LoggerHandle,
        template: str,
        *args: object,
        exc_info: object | None = None,
    ) -> None:
        """Emit one formatted message through the logging port."""


def get_logger(name: str) -> LoggerHandle:
    """Return an opaque logging-port handle for *name*.

    Parameters
    ----------
    name : str
        Logger name, normally ``__name__``.

    Returns
    -------
    LoggerHandle
        Handle accepted by the ``log_*`` helpers.
    """
    return LoggerHandle(typ.cast("_CompatibleLogger", _get_femtologger(name)))


getLogger = get_logger  # ruff: ignore[mixed-case-variable-in-global-scope]  # Preserve the stdlib-compatible constructor alias.


def _format_message(template: str, args: tuple[object, ...]) -> str:
    """Format a log message template."""
    return template % args if args else template


def _emit(
    logger: LoggerHandle,
    log_call: _LogCall,
) -> None:
    """Format and dispatch one log request through the wrapped backend."""
    level = log_call.level
    convenience_method = log_call.convenience_method
    message = _format_message(log_call.template, log_call.args)
    exc_info = log_call.exc_info
    backend = logger._logger
    try:
        method = getattr(
            typ.cast("_SupportsConvenienceLog", backend), convenience_method
        )
    except AttributeError:
        typ.cast("_SupportsLogMethod", backend).log(
            level,
            message,
            exc_info=exc_info,
            stack_info=False,
        )
        return
    try:
        method(message, exc_info=exc_info, stack_info=False)
    except TypeError:
        # Limit the DEBUG compatibility retry to signature mismatches so an
        # internal TypeError after emission cannot duplicate a record.
        if level != logging.DEBUG or not _method_rejects_logging_call(
            method,
            message,
            exc_info=exc_info,
        ):
            raise
        log_method = getattr(backend, "log", None)
        if not callable(log_method):
            raise
        log_method(level, message, exc_info=exc_info, stack_info=False)


def _make_log_wrapper(
    config: _LogWrapperConfig,
    *,
    summary: str,
) -> _LogWrapper:
    """Build a documented public wrapper bound to one backend level."""

    def emit(
        logger: LoggerHandle,
        template: str,
        *args: object,
        exc_info: object | None = config.default_exc_info,
    ) -> None:
        """Emit one message at the bound level through the logging port."""
        _emit(
            logger,
            _LogCall(
                config.level,
                config.convenience_method,
                template,
                args,
                exc_info,
            ),
        )

    emit.__name__ = config.name
    emit.__qualname__ = config.name
    exception_description = "Exception information to attach to the log record."
    if config.default_exc_info is True:
        exception_description += " Defaults to ``True`` to record the active exception."
    emit.__doc__ = (
        f"{summary}\n\n"
        "Parameters\n"
        "----------\n"
        "logger : LoggerHandle\n"
        "    Opaque handle returned by :func:`get_logger`.\n"
        "template : str\n"
        "    Percent-style format string for the log message.\n"
        "*args : object\n"
        "    Arguments interpolated into the template.\n"
        "exc_info : object | None, optional\n"
        f"    {exception_description}\n\n"
        "Returns\n"
        "-------\n"
        "None\n"
        "    This wrapper emits the message without returning a value."
    )
    return emit


log_debug: _LogWrapper = _make_log_wrapper(
    _LogWrapperConfig(
        name="log_debug",
        level=logging.DEBUG,
        convenience_method="debug",
    ),
    summary="Format and emit a DEBUG message through the logging port.",
)
log_info: _LogWrapper = _make_log_wrapper(
    _LogWrapperConfig(
        name="log_info",
        level=logging.INFO,
        convenience_method="info",
    ),
    summary="Format and emit an INFO message through the logging port.",
)
log_warning: _LogWrapper = _make_log_wrapper(
    _LogWrapperConfig(
        name="log_warning",
        level=logging.WARNING,
        convenience_method="warning",
    ),
    summary="Format and emit a WARNING message through the logging port.",
)
log_error: _LogWrapper = _make_log_wrapper(
    _LogWrapperConfig(
        name="log_error",
        level=logging.ERROR,
        convenience_method="error",
    ),
    summary="Format and emit an ERROR message through the logging port.",
)
log_exception: _LogWrapper = _make_log_wrapper(
    _LogWrapperConfig(
        name="log_exception",
        level=logging.ERROR,
        convenience_method="exception",
        default_exc_info=True,
    ),
    summary="Format and emit an exception message with traceback data.",
)


# Keep the raw backend private to this module. The public structured-event
# helper is itself part of the logging port and preserves the historical API.
_event_log = typ.cast("_CompatibleLogger", _get_femtologger(__name__))


def _serialize_log_field(value: object) -> object:
    """Return a stable JSON-compatible representation for a log field."""
    match value:
        case enum.Enum():
            return value.value
        case dt.date() | dt.time():
            return value.isoformat()
        case _:
            return str(value)


def format_log_event(event_name: str, /, **fields: object) -> str:
    """Serialize one structured event as stable JSON text.

    The event name takes precedence over an ``event`` key in ``fields``.
    Common non-JSON values, including enums and date/time objects, use the
    same normalization as :func:`log_event`.

    Parameters
    ----------
    event_name : str
        Event name to store in the JSON ``"event"`` field.
    **fields : object
        Additional event fields to serialize.

    Returns
    -------
    str
        A sorted JSON object containing the event name and fields.

    Examples
    --------
    >>> format_log_event("generation.started", workflow_id="workflow-42")
    '{"event": "generation.started", "workflow_id": "workflow-42"}'
    """
    payload = {**fields, "event": event_name}
    return json.dumps(payload, default=_serialize_log_field, sort_keys=True)


def log_event(level: str, message: str, **fields: object) -> None:
    """Emit one structured log event through the port.

    Logger convenience methods accept only ``exc_info`` and ``stack_info``
    beside the message. Other fields are serialized as JSON.

    Parameters
    ----------
    level : str
        Logger method name, such as ``"info"`` or ``"error"``.
    message : str
        Event name, retained as the JSON ``"event"`` value when fields exist.
    **fields : object
        Exception metadata is passed through; other fields are included in the
        serialized event message.

    Examples
    --------
    >>> log_event("info", "generation.started", workflow_id="workflow-42")
    # Logger message: {"event": "generation.started", "workflow_id": "workflow-42"}
    """
    log_method = getattr(_event_log, level)
    allowed_kwargs = {
        key: value for key, value in fields.items() if key in {"exc_info", "stack_info"}
    }
    extra_fields = {
        key: value for key, value in fields.items() if key not in allowed_kwargs
    }
    if extra_fields:
        log_method(
            format_log_event(message, **extra_fields),
            **allowed_kwargs,
        )
        return
    try:
        log_method(message, **allowed_kwargs)
    except TypeError:
        log_method(format_log_event(message), **allowed_kwargs)


__all__ = (
    "LogLevel",
    "LoggerHandle",
    "configure_logging",
    "format_log_event",
    "getLogger",
    "get_logger",
    "log_debug",
    "log_error",
    "log_event",
    "log_exception",
    "log_info",
    "log_warning",
)
