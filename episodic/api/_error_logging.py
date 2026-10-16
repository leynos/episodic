"""Credential-safe logging helpers for HTTP error mappers."""

import itertools
import pathlib as pl
import traceback
import typing as typ
import uuid

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
    elif type(entity_id) is uuid.UUID:
        safe_entity_id = str(entity_id)
    elif type(entity_id) is str:
        try:
            parsed_entity_id = uuid.UUID(entity_id)
        except ValueError:
            safe_entity_id = "<redacted>"
        else:
            canonical_entity_id = str(parsed_entity_id)
            safe_entity_id = (
                canonical_entity_id
                if entity_id.lower() == canonical_entity_id
                else "<redacted>"
            )
    else:
        safe_entity_id = "<redacted>"
    return (safe_code, safe_entity_id)


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

    frame_summaries = traceback.StackSummary.extract(
        itertools.islice(
            traceback.walk_tb(source_traceback),
            _MAX_LOGGED_SOURCE_FRAMES + 1,
        ),
        lookup_lines=False,
        capture_locals=False,
    )
    omitted_frames = len(frame_summaries) > _MAX_LOGGED_SOURCE_FRAMES
    visible_frames = frame_summaries[:_MAX_LOGGED_SOURCE_FRAMES]
    frame_labels = [
        f"{pl.PurePath(frame.filename).name}:{frame.name}:{frame.lineno}"
        for frame in visible_frames
    ]
    if omitted_frames:
        frame_labels.append("...")
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
