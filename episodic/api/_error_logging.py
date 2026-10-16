"""Credential-safe logging helpers for HTTP error mappers."""

import pathlib as pl
import traceback
import typing as typ

if typ.TYPE_CHECKING:
    import collections.abc as cabc
    import types


class _RedactedMapperError(Exception):
    """Carry redacted source-frame metadata without original traceback frames."""


def _safe_source_frame_metadata(
    source_traceback: types.TracebackType | None,
) -> str:
    """Format source locations without retaining frames, source lines, or locals."""
    if source_traceback is None:
        return "unavailable"

    frame_summaries = traceback.StackSummary.extract(
        traceback.walk_tb(source_traceback),
        lookup_lines=False,
        capture_locals=False,
    )
    return " <- ".join(
        f"{pl.PurePath(frame.filename).name}:{frame.name}:{frame.lineno}"
        for frame in frame_summaries
    )


def _log_unmapped_error(
    emit_error: cabc.Callable[..., None],
    source_traceback: types.TracebackType | None,
    template: str,
    *args: object,
) -> None:
    """Log safe source locations with isolated redacted exception information.

    Keep ``emit_error`` inside this exception handler: ``exc_info=True`` reads
    the synthetic redacted exception through ``sys.exc_info()``. Source frames
    are reduced to filename, function, and line metadata before emission.
    """
    frame_metadata = _safe_source_frame_metadata(source_traceback)
    del source_traceback
    redacted = _RedactedMapperError(
        f"Original exception message redacted. Source frames: {frame_metadata}"
    )
    try:
        raise redacted from None
    except _RedactedMapperError as safe_exc:
        safe_exc.__cause__ = None
        safe_exc.__context__ = None
        emit_error(template, *args, exc_info=True)
