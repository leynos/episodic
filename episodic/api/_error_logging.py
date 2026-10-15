"""Credential-safe logging helpers for HTTP error mappers."""

import typing as typ

if typ.TYPE_CHECKING:
    import collections.abc as cabc


class _RedactedMapperError(Exception):
    """Carry mapper traceback frames without retaining exception messages."""


def _log_unmapped_error(
    emit_error: cabc.Callable[..., None],
    exc: Exception,
    template: str,
    *args: object,
) -> None:
    """Log safe metadata and traceback frames without exception text or chains.

    Keep ``emit_error`` inside this exception handler: ``exc_info=True`` reads
    the active exception through ``sys.exc_info()``.
    """
    redacted = _RedactedMapperError("Original exception message redacted.")
    try:
        raise redacted.with_traceback(exc.__traceback__) from None
    except _RedactedMapperError as safe_exc:
        safe_exc.__cause__ = None
        safe_exc.__context__ = None
        emit_error(template, *args, exc_info=True)
