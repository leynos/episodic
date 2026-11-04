"""Private protocols and dispatch support used by the logging port."""

import inspect
import typing as typ


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


type _ConvenienceMethod = typ.Literal[
    "debug",
    "info",
    "warning",
    "error",
    "exception",
]


class _LogCall(typ.NamedTuple):
    """One formatted log request ready for backend dispatch."""

    level: int
    convenience_method: _ConvenienceMethod
    template: str
    args: tuple[object, ...]
    exc_info: object | None


class _LogWrapperConfig(typ.NamedTuple):
    """Bind the public name and backend dispatch for one logging wrapper."""

    name: str
    level: int
    convenience_method: _ConvenienceMethod
    default_exc_info: object | None = None


def _method_rejects_logging_call(
    method: object,
    message: str,
    *,
    exc_info: object | None,
) -> bool:
    """Return whether an inspectable method rejects the helper arguments."""
    if not callable(method):
        return False
    try:
        signature = inspect.signature(method)
    except (TypeError, ValueError):  # fmt: skip
        return False
    try:
        signature.bind(message, exc_info=exc_info, stack_info=False)
    except TypeError:
        return True
    return False
