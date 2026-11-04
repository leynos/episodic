"""Private backend protocols shared by the logging port."""

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
