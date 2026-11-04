"""Build and emit credential-safe diagnostics for unmapped HTTP errors.

Mappers create immutable diagnostic metadata without logging. The central
Falcon error serializer emits that metadata through its injected logging port.
The detached exception information contains neither the original exception
nor its traceback frames, locals, source lines, or source message. Source
locations are limited to 20 frame labels. Profile metadata permits only known
codes and canonical UUID entity IDs; other values are redacted.
"""

import dataclasses as dc
import pathlib as pl
import traceback
import typing as typ
import uuid
from collections import deque

if typ.TYPE_CHECKING:
    import types

    from episodic.canonical.profile_templates.types import ProfileTemplateError

    from .dependencies import UnmappedErrorEmitter


@dc.dataclass(frozen=True, slots=True)
class _UnmappedErrorDiagnostic:
    """Carry safe message fields and detached exception info to serialization."""

    template: str
    args: tuple[object, ...]
    exc_info: tuple[type[BaseException], BaseException, None]


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


def _profile_template_error_diagnostic(
    source_exception: ProfileTemplateError,
    entity_id: object | None,
) -> _UnmappedErrorDiagnostic:
    """Build safe profile-template diagnostics without retaining source values."""
    safe_code, safe_entity_id = _safe_profile_template_log_metadata(
        source_exception.code,
        entity_id,
    )
    return _unmapped_error_diagnostic(
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


def _unmapped_error_diagnostic(
    source_traceback: types.TracebackType | None,
    template: str,
    *args: object,
) -> _UnmappedErrorDiagnostic:
    """Build detached exception information and safe source locations."""
    frame_metadata = _safe_source_frame_metadata(source_traceback)
    del source_traceback
    redacted = _RedactedMapperError(
        f"Original exception message redacted. Source frames: {frame_metadata}"
    )
    safe_exception_info = (type(redacted), redacted, None)
    return _UnmappedErrorDiagnostic(template, args, safe_exception_info)


def _emit_unmapped_error_diagnostic(
    emit_error: UnmappedErrorEmitter,
    diagnostic: _UnmappedErrorDiagnostic,
) -> None:
    """Emit a sanitized diagnostic at the central API error boundary."""
    emit_error(
        diagnostic.template,
        *diagnostic.args,
        exc_info=diagnostic.exc_info,
    )
