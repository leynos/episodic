"""Chapter-marker generation aligned to script segments.

This module implements a chapter-marker generator that derives podcast player
navigation points from TEI P5 podcast scripts and segment-transition metadata.
It uses the existing LLM port and enriches canonical TEI bodies with a
``<div type="chapters">`` metadata block.
"""

import dataclasses as dc
import json
import re
import typing as typ

import tei_rapporteur as tei

from episodic.generation.tei_payload import (
    body_blocks_payload,
    build_text_inline,
    is_div_payload,
    require_mapping,
    require_non_empty_str_value,
    require_sequence,
)
from episodic.llm import (
    LLMPort,
    LLMProviderOperation,
    LLMRequest,
    LLMResponse,
    LLMTokenBudget,
    LLMUsage,
)
from episodic.logging import get_logger, log_info

type JsonMapping = dict[str, object]

logger = get_logger(__name__)

_DEFAULT_SYSTEM_PROMPT = (
    "The assistant acts as a podcast chapter-marker generator. Given a TEI P5 "
    "podcast script and segment-transition metadata, create playback chapter "
    "markers aligned to segment starts. Return JSON only with key "
    '"chapters". Each chapter must include "title" and "start". The "start" '
    "value must be a non-negative ISO 8601-style duration in the form "
    "PT#H#M#S with integer hours, minutes, and seconds only (for example: "
    "PT0S, PT5M30S, PT1H2M3S). Days and fractional units are not allowed. "
    "Optional fields: summary, end, duration, and tei_locator."
)

_SUPPORTED_DURATION_MESSAGE = (
    "must be a non-negative ISO 8601-style duration in the form PT#H#M#S "
    "with integer hours, minutes, and seconds only."
)

_ISO_8601_DURATION_PATTERN = re.compile(
    r"^P(?=.*\d[HMS])T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?"
    r"(?:(?P<seconds>\d+)S)?$"
)


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
    summary: str = ""
    end: str | None = None
    duration: str | None = None
    tei_locator: str | None = None

    def __post_init__(self) -> None:
        """Validate required chapter fields and normalize optional metadata."""
        _ensure_non_empty_field(self, "title")
        _duration_to_seconds(self.start, "start")
        if not isinstance(self.summary, str):
            msg = "summary must be a string."
            raise TypeError(msg)
        object.__setattr__(self, "summary", self.summary.strip())
        end = _normalize_optional_string(self.end, "end")
        duration = _normalize_optional_string(self.duration, "duration")
        tei_locator = _normalize_optional_string(self.tei_locator, "tei_locator")
        if end is not None:
            _duration_to_seconds(end, "end")
        if duration is not None:
            _duration_to_seconds(duration, "duration")
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
    summary = _require_optional_string(raw.get("summary"), "summary") or ""
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


@dc.dataclass(frozen=True, slots=True)
class _SegmentTransition:
    """One explicit segment transition supplied to the chapter generator."""

    start: str
    locator_keys: frozenset[str]


def _locator_keys_for_segment(raw: dict[str, object]) -> frozenset[str]:
    """Return locator keys by which a chapter may refer to a segment."""
    keys: set[str] = set()
    for field_name in ("id", "xml_id", "xml:id", "tei_locator", "locator"):
        value = raw.get(field_name)
        if isinstance(value, str) and value.strip():
            locator = value.strip()
            keys.add(locator)
            keys.add(locator.removeprefix("#"))
            keys.add(f"#{locator.removeprefix('#')}")
    return frozenset(keys)


def _transitions_from_dict(
    mapping: dict[str, object],
) -> tuple[_SegmentTransition, ...]:
    """Yield transitions rooted at a dict node, then recurse into its values."""
    transitions: list[_SegmentTransition] = []
    start = mapping.get("start")
    if isinstance(start, str) and start.strip():
        transitions.append(
            _SegmentTransition(
                start=start.strip(),
                locator_keys=_locator_keys_for_segment(mapping),
            )
        )
    for nested_value in mapping.values():
        transitions.extend(_segment_transitions_from_value(nested_value))
    return tuple(transitions)


def _transitions_from_sequence(
    items: typ.Sequence[object],
) -> tuple[_SegmentTransition, ...]:
    """Recurse into each element of a list node."""
    transitions: list[_SegmentTransition] = []
    for item in items:
        transitions.extend(_segment_transitions_from_value(item))
    return tuple(transitions)


def _segment_transitions_from_value(value: object) -> tuple[_SegmentTransition, ...]:
    """Extract explicit segment starts from nested segment metadata."""
    if isinstance(value, dict):
        mapping = typ.cast("dict[str, object]", value)
        return _transitions_from_dict(mapping)
    if isinstance(value, list):
        items = typ.cast("typ.Sequence[object]", value)
        return _transitions_from_sequence(items)
    return ()


def _validate_segment_transition_starts(
    transitions: tuple[_SegmentTransition, ...],
) -> None:
    """Raise if any transition start is unparseable."""
    for transition in transitions:
        try:
            _duration_to_seconds(transition.start, "segment start")
        except (TypeError, ValueError) as exc:
            raise ChapterMarkersResponseFormatError(str(exc)) from exc


def _build_segment_start_lookups(
    transitions: tuple[_SegmentTransition, ...],
) -> tuple[set[int], dict[str, tuple[int, str]]]:
    """Build a start-value set and a locator-to-start mapping from transitions."""
    starts: set[int] = set()
    starts_by_locator: dict[str, tuple[int, str]] = {}
    for transition in transitions:
        start_secs = _duration_to_seconds(transition.start, "segment start")
        starts.add(start_secs)
        locator_value = (start_secs, transition.start)
        for locator_key in transition.locator_keys:
            existing_value = starts_by_locator.get(locator_key)
            if existing_value is not None and existing_value != locator_value:
                raise ChapterMarkersResponseFormatError(  # noqa: TRY003 - include the conflicting locator key.
                    f"Conflicting locator reuse for {locator_key!r}."
                )
            starts_by_locator[locator_key] = locator_value
    return starts, starts_by_locator


def _validate_chapters_align_to_segments(
    result: ChapterMarkersResult,
    segment_structure: JsonMapping | None,
) -> None:
    """Validate generated chapter markers against explicit segment starts."""
    if segment_structure is None:
        return
    transitions = _segment_transitions_from_value(segment_structure)
    if not transitions:
        return
    _validate_segment_transition_starts(transitions)
    starts, starts_by_locator = _build_segment_start_lookups(transitions)
    for chapter in result.chapters:
        _validate_chapter_aligns_to_segments(chapter, starts, starts_by_locator)


def _validate_chapter_aligns_to_segments(
    chapter: ChapterMarker,
    starts: set[int],
    starts_by_locator: dict[str, tuple[int, str]],
) -> None:
    """Validate one generated chapter against explicit segment metadata."""
    chapter_start = _duration_to_seconds(chapter.start, "start")
    if chapter_start not in starts:
        msg = (
            "chapter starts must align to supplied segment starts; "
            f"{chapter.start} is not a segment transition."
        )
        raise ChapterMarkersResponseFormatError(msg)
    if chapter.tei_locator is None:
        return
    segment_start_entry = starts_by_locator.get(chapter.tei_locator)
    if segment_start_entry is None:
        msg = (
            "chapter locators must resolve to supplied segment metadata; "
            f"{chapter.tei_locator} is not a known segment locator."
        )
        raise ChapterMarkersResponseFormatError(msg)
    segment_start, segment_start_text = segment_start_entry
    if chapter_start != segment_start:
        msg = (
            "chapter locators must align to supplied segment starts; "
            f"{chapter.tei_locator} starts at {segment_start_text}, not "
            f"{chapter.start}."
        )
        raise ChapterMarkersResponseFormatError(msg)


@dc.dataclass(frozen=True, slots=True)
class ChapterMarkersGenerator:
    """Chapter-marker generator service backed by an LLM."""

    llm: LLMPort
    config: ChapterMarkersGeneratorConfig

    @staticmethod
    def build_prompt(
        script_tei_xml: str,
        *,
        segment_structure: JsonMapping | None = None,
    ) -> str:
        """Build the user prompt for chapter-marker extraction."""
        prompt_payload: JsonMapping = {"script_tei_xml": script_tei_xml}
        if segment_structure is not None:
            prompt_payload["segment_structure"] = segment_structure
        return json.dumps(prompt_payload, indent=2)

    @staticmethod
    def _result_from_response(response: LLMResponse) -> ChapterMarkersResult:
        """Parse an LLM response into a ChapterMarkersResult."""
        try:
            payload = json.loads(response.text)
        except json.JSONDecodeError as exc:
            msg = "LLM response is not valid JSON."
            logger.warning("chapter_markers_response_invalid_json")
            raise ChapterMarkersResponseFormatError(msg) from exc

        payload_dict = _decode_object(payload, "response")
        chapters_raw = _require_list(payload_dict.get("chapters"), "chapters")
        chapters = tuple(
            _parse_chapter(_decode_object(chapter, "chapter"))
            for chapter in chapters_raw
        )
        try:
            result = ChapterMarkersResult(
                chapters=chapters,
                usage=response.usage,
                model=response.model,
                provider_response_id=response.provider_response_id,
                finish_reason=response.finish_reason,
            )
        except ValueError as exc:
            logger.warning("chapter_markers_response_invalid_timing")
            raise ChapterMarkersResponseFormatError(str(exc)) from exc
        log_info(
            logger,
            "chapter_markers_response_parsed chapter_count=%s",
            len(result.chapters),
        )
        return result

    async def generate(
        self,
        script_tei_xml: str,
        *,
        segment_structure: JsonMapping | None = None,
    ) -> ChapterMarkersResult:
        """Generate chapter markers from a TEI script body."""
        prompt = self.build_prompt(
            script_tei_xml,
            segment_structure=segment_structure,
        )
        request = LLMRequest(
            model=self.config.model,
            prompt=prompt,
            system_prompt=self.config.system_prompt,
            provider_operation=self.config.provider_operation,
            token_budget=self.config.token_budget,
        )
        logger.info("chapter_markers_generation_requested")
        response = await self.llm.generate(request)
        result = self._result_from_response(response)
        _validate_chapters_align_to_segments(result, segment_structure)
        return result


def _build_item_payload(chapter: ChapterMarker) -> dict[str, object]:
    """Build one list-item payload from a `ChapterMarker`."""
    item_payload: dict[str, object] = {
        "label": {"content": build_text_inline(chapter.title)},
        "content": build_text_inline(chapter.summary or "."),
        "n": chapter.start,
    }
    if chapter.tei_locator is not None:
        item_payload["corresp"] = [chapter.tei_locator]
    return item_payload


def _build_chapters_div_payload(
    chapters: tuple[ChapterMarker, ...],
) -> dict[str, object]:
    """Build the structured TEI payload for the chapters div."""
    return {
        "type": "div",
        "div_type": "chapters",
        "content": [
            {
                "type": "list",
                "items": [_build_item_payload(chapter) for chapter in chapters],
            }
        ],
    }


def enrich_tei_with_chapter_markers(
    tei_xml: str,
    result: ChapterMarkersResult,
) -> str:
    """Insert chapter-marker metadata into a TEI document body."""
    document = tei.parse_xml(tei_xml)
    document_payload = typ.cast("dict[str, object]", tei.to_dict(document))
    body_blocks = body_blocks_payload(document_payload)
    original_block_count = len(body_blocks)
    body_blocks[:] = [
        body_block
        for body_block in body_blocks
        if not is_div_payload(body_block, "chapters")
    ]
    removed_block_count = original_block_count - len(body_blocks)
    if result.chapters:
        body_blocks.append(_build_chapters_div_payload(result.chapters))
    elif removed_block_count == 0:
        return tei_xml
    log_info(
        logger,
        "chapter_markers_tei_enriched chapter_count=%s removed_chapter_blocks=%s",
        len(result.chapters),
        removed_block_count,
    )
    enriched_document = tei.from_dict(document_payload)
    return tei.emit_xml(enriched_document)
