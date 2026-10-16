"""Build credential-safe diagnostics for unmapped HTTP error logging.

Mappers use ``_log_unmapped_error`` with the logging port and safe, percent-style
fields. Its emitted ``exc_info`` is detached: it contains neither the original
exception nor its traceback frames, locals, source lines, or source message.
Source locations are limited to 20 frame labels. Profile metadata permits only
known codes and normalized canonical UUID entity IDs; other values are redacted.

For example, a mapper can pass ``exc.__traceback__`` and the exception type to
``_log_unmapped_error``; the helper emits only the redacted diagnostic.
"""

import pathlib as pl
import traceback
import typing as typ
import uuid
from collections import deque

if typ.TYPE_CHECKING:
    import collections.abc as cabc
    import types

    from episodic.canonical.profile_templates.types import ProfileTemplateError

_SAFE_PROFILE_TEMPLATE_LOG_CODES = frozenset({
    "profile_template_error",
    "entity_not_found",
    "revision_conflict",
    "internal_error",
})
_MAX_LOGGED_SOURCE_FRAMES = 20


class _RedactedMapperError(Exception):
    """Carry redacted source-frame metadata without original traceback frames."""


def _safe_profile_template_log_metadata(
    code: object,
    entity_id: object | None,
) -> tuple[str, str]:
    """Expose known profile-template codes and UUID identifiers in diagnostics."""
    safe_code = (
        code
        if type(code) is str and code in _SAFE_PROFILE_TEMPLATE_LOG_CODES
        else "<redacted>"
    )
    if entity_id is None:
        safe_entity_id = "None"
    else:
        safe_entity_id = _safe_profile_template_entity_id(entity_id) or "<redacted>"
    return (safe_code, safe_entity_id)


def _safe_profile_template_entity_id(entity_id: object | None) -> str | None:
    """Return a canonical UUID string, omitting untrusted identifiers."""
    if entity_id is None:
        return None
    if type(entity_id) is uuid.UUID:
        return str(entity_id)
    if type(entity_id) is str:
        try:
            parsed_entity_id = uuid.UUID(entity_id)
        except ValueError:
            return None
        canonical_entity_id = str(parsed_entity_id)
        return canonical_entity_id if entity_id.lower() == canonical_entity_id else None
    return None


def _log_unmapped_profile_template_error(
    emit_error: cabc.Callable[..., None],
    source_exception: ProfileTemplateError,
    entity_id: object | None,
) -> None:
    """Log profile-template metadata only after applying its safe-value policy."""
    safe_code, safe_entity_id = _safe_profile_template_log_metadata(
        source_exception.code,
        entity_id,
    )
    _log_unmapped_error(
        emit_error,
        source_exception.__traceback__,
        "Unmapped profile/template error: type=%s code=%s entity_id=%s",
        type(source_exception).__name__,
        safe_code,
        safe_entity_id,
    )


def _safe_source_frame_metadata(
    source_traceback: types.TracebackType | None,
) -> str:
    """Format source locations without retaining frames, source lines, or locals."""
    if source_traceback is None:
        return "unavailable"

    source_frames = deque(
        traceback.walk_tb(source_traceback),
        maxlen=_MAX_LOGGED_SOURCE_FRAMES + 1,
    )
    omitted_frames = len(source_frames) > _MAX_LOGGED_SOURCE_FRAMES
    if omitted_frames:
        source_frames.popleft()

    frame_summaries = traceback.StackSummary.extract(
        source_frames,
        lookup_lines=False,
        capture_locals=False,
    )
    frame_labels = [
        f"{pl.PurePath(frame.filename).name}:{frame.name}:{frame.lineno}"
        for frame in frame_summaries
    ]
    if omitted_frames:
        frame_labels.insert(0, "...")
    return " <- ".join(frame_labels)


def _log_unmapped_error(
    emit_error: cabc.Callable[..., None],
    source_traceback: types.TracebackType | None,
    template: str,
    *args: object,
) -> None:
    """Log detached exception information and safe source locations."""
    frame_metadata = _safe_source_frame_metadata(source_traceback)
    del source_traceback
    redacted = _RedactedMapperError(
        f"Original exception message redacted. Source frames: {frame_metadata}"
    )
    safe_exception_info = (type(redacted), redacted, None)
    emit_error(template, *args, exc_info=safe_exception_info)
