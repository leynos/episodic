"""DTOs and response parsing validation for chapter markers."""

import dataclasses as dc

from episodic.generation.chapter_marker_common import (
    _DEFAULT_SYSTEM_PROMPT,
    _ISO_8601_DURATION_PATTERN,
    _SUPPORTED_DURATION_MESSAGE,
)
from episodic.generation.tei_payload import (
    require_mapping,
    require_non_empty_str_value,
    require_sequence,
)
from episodic.llm import LLMProviderOperation, LLMTokenBudget, LLMUsage


class ChapterMarkersResponseFormatError(ValueError):
    """Raised when an LLM response cannot be parsed into chapter markers."""


def _duration_to_seconds(duration: str, field_name: str) -> int:
    """Return a supported integer PT#H#M#S duration as seconds."""
    if not isinstance(duration, str):
        msg = f"{field_name} {_SUPPORTED_DURATION_MESSAGE}"
        raise TypeError(msg)
    match = _ISO_8601_DURATION_PATTERN.fullmatch(duration)
    if match is None:
        msg = f"{field_name} {_SUPPORTED_DURATION_MESSAGE}"
        raise ValueError(msg)
    hours = int(match.group("hours") or "0")
    minutes = int(match.group("minutes") or "0")
    seconds = int(match.group("seconds") or "0")
    return (hours * 3600) + (minutes * 60) + seconds


def _ensure_non_empty_field(instance: object, field_name: str) -> None:
    """Reject blank or whitespace-only string fields on a dataclass instance."""
    require_non_empty_str_value(
        getattr(instance, field_name),
        field_name,
        error_cls=ValueError,
        message="must be non-empty.",
    )


def _normalize_optional_string(value: object, field_name: str) -> str | None:
    """Normalize blank optional strings to None and strip surrounding whitespace."""
    if value is None:
        return None
    if not isinstance(value, str):
        msg = f"{field_name} must be a string or null."
        raise TypeError(msg)
    normalized = value.strip()
    if normalized == "":
        return None
    return normalized


@dc.dataclass(frozen=True, slots=True)
class ChapterMarker:
    """A single podcast chapter marker aligned to a script segment transition."""

    title: str
    start: str
    summary: str | None = None
    end: str | None = None
    duration: str | None = None
    tei_locator: str | None = None

    def __post_init__(self) -> None:
        """Validate required chapter fields and normalize optional metadata."""
        _ensure_non_empty_field(self, "title")
        _duration_to_seconds(self.start, "start")
        summary = _normalize_optional_string(self.summary, "summary")
        end = _normalize_optional_string(self.end, "end")
        duration = _normalize_optional_string(self.duration, "duration")
        tei_locator = _normalize_optional_string(self.tei_locator, "tei_locator")
        if end is not None:
            _duration_to_seconds(end, "end")
        if duration is not None:
            _duration_to_seconds(duration, "duration")
        object.__setattr__(self, "summary", summary)
        object.__setattr__(self, "end", end)
        object.__setattr__(self, "duration", duration)
        object.__setattr__(self, "tei_locator", tei_locator)


@dc.dataclass(frozen=True, slots=True)
class ChapterMarkersResult:
    """Chapter-marker generation result with structured entries and metadata."""

    chapters: tuple[ChapterMarker, ...]
    usage: LLMUsage
    model: str = ""
    provider_response_id: str = ""
    finish_reason: str | None = None

    def __post_init__(self) -> None:
        """Reject duplicate or descending chapter starts."""
        previous_start: int | None = None
        for chapter in self.chapters:
            current_start = _duration_to_seconds(chapter.start, "start")
            if previous_start is not None and current_start <= previous_start:
                msg = "chapter starts must be strictly increasing."
                raise ValueError(msg)
            previous_start = current_start


@dc.dataclass(frozen=True, slots=True)
class ChapterMarkersGeneratorConfig:
    """Configuration for the chapter-marker generator service."""

    model: str
    provider_operation: LLMProviderOperation | str = (
        LLMProviderOperation.CHAT_COMPLETIONS
    )
    token_budget: LLMTokenBudget | None = None
    system_prompt: str = _DEFAULT_SYSTEM_PROMPT


def _decode_object(value: object, field_name: str) -> dict[str, object]:
    """Decode a JSON value as a dictionary or raise a format error."""
    return require_mapping(
        value,
        field_name,
        error_cls=ChapterMarkersResponseFormatError,
    )


def _require_non_empty_string(value: object, field_name: str) -> str:
    """Require a non-empty string value or raise a format error."""
    return require_non_empty_str_value(
        value,
        field_name,
        error_cls=ChapterMarkersResponseFormatError,
    ).strip()


def _require_optional_string(value: object, field_name: str) -> str | None:
    """Return *value* typed as ``str | None``."""
    if value is not None and not isinstance(value, str):
        msg = f"{field_name} must be a string or null."
        raise ChapterMarkersResponseFormatError(msg)
    return value if isinstance(value, str) else None


def _require_list(value: object, field_name: str) -> list[object]:
    """Require a list value or raise a format error."""
    return require_sequence(
        value,
        field_name,
        error_cls=ChapterMarkersResponseFormatError,
    )


def _parse_chapter(raw: dict[str, object]) -> ChapterMarker:
    """Parse a single chapter marker from a JSON payload."""
    title = _require_non_empty_string(raw.get("title"), "title")
    start = _require_non_empty_string(raw.get("start"), "start")
    summary = _require_optional_string(raw.get("summary"), "summary")
    end = _require_optional_string(raw.get("end"), "end")
    duration = _require_optional_string(raw.get("duration"), "duration")
    tei_locator = _require_optional_string(raw.get("tei_locator"), "tei_locator")
    try:
        return ChapterMarker(
            title=title,
            start=start,
            summary=summary,
            end=end,
            duration=duration,
            tei_locator=tei_locator,
        )
    except (TypeError, ValueError) as exc:
        raise ChapterMarkersResponseFormatError(str(exc)) from exc
