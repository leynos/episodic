"""Segment traversal and alignment validation for chapter markers."""

import dataclasses as dc
import typing as typ

from episodic.generation.chapter_marker_models import (
    ChapterMarker,
    ChapterMarkersResponseFormatError,
    ChapterMarkersResult,
    _duration_to_seconds,
)

if typ.TYPE_CHECKING:
    from episodic.generation.chapter_marker_common import JsonMapping


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


_MAX_SEGMENT_TRAVERSAL_DEPTH: int = 20


def _make_segment_transition_if_present(
    mapping: dict[str, object],
) -> _SegmentTransition | None:
    """Return a SegmentTransition for a mapping that contains a start field, or None."""
    start = mapping.get("start")
    if isinstance(start, str) and start.strip():
        return _SegmentTransition(
            start=start.strip(),
            locator_keys=_locator_keys_for_segment(mapping),
        )
    return None


def _check_traversal_depth(depth: int, caller: str) -> None:
    """Raise ChapterMarkersResponseFormatError when the traversal depth is exhausted."""
    if depth <= 0:
        msg = f"{caller} traversal depth exhausted: depth={depth}."
        raise ChapterMarkersResponseFormatError(msg)


def _transitions_from_dict(
    mapping: dict[str, object],
    *,
    depth: int,
) -> tuple[_SegmentTransition, ...]:
    """Yield transitions rooted at a dict node, then recurse into its values."""
    transitions: list[_SegmentTransition] = []
    transition = _make_segment_transition_if_present(mapping)
    if transition is not None:
        transitions.append(transition)
    for nested_value in mapping.values():
        if not isinstance(nested_value, dict | list):
            continue
        _check_traversal_depth(depth, "_transitions_from_dict")
        transitions.extend(
            _segment_transitions_from_value(nested_value, depth=depth - 1)
        )
    return tuple(transitions)


def _transitions_from_sequence(
    items: typ.Sequence[object],
    *,
    depth: int,
) -> tuple[_SegmentTransition, ...]:
    """Recurse into each element of a list node."""
    _check_traversal_depth(depth, "_transitions_from_sequence")
    transitions: list[_SegmentTransition] = []
    for item in items:
        transitions.extend(_segment_transitions_from_value(item, depth=depth - 1))
    return tuple(transitions)


def _segment_transitions_from_value(
    value: object,
    *,
    depth: int = _MAX_SEGMENT_TRAVERSAL_DEPTH,
) -> tuple[_SegmentTransition, ...]:
    """Extract explicit segment starts from nested segment metadata."""
    if depth < 0:
        msg = (
            f"_segment_transitions_from_value traversal depth exhausted: depth={depth}."
        )
        raise ChapterMarkersResponseFormatError(msg)
    if isinstance(value, dict):
        mapping = typ.cast("dict[str, object]", value)
        return _transitions_from_dict(mapping, depth=depth)
    if isinstance(value, list):
        items = typ.cast("typ.Sequence[object]", value)
        return _transitions_from_sequence(items, depth=depth)
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


def _check_locator_conflict(
    locator_key: str,
    existing: tuple[int, str] | None,
    start_secs: int,
    start_text: str,
) -> None:
    """Raise if a locator key maps to two different segment starts."""
    if existing is not None and existing[0] != start_secs:
        raise ChapterMarkersResponseFormatError(  # noqa: TRY003
            f"Conflicting locator reuse for {locator_key!r}: "
            f"{existing[1]!r} and {start_text!r}."
        )


def _build_segment_start_lookups(
    transitions: tuple[_SegmentTransition, ...],
) -> tuple[set[int], dict[str, tuple[int, str]]]:
    """Build a start-value set and a locator-to-start mapping from transitions."""
    starts: set[int] = set()
    starts_by_locator: dict[str, tuple[int, str]] = {}
    for transition in transitions:
        start_secs = _duration_to_seconds(transition.start, "segment start")
        starts.add(start_secs)
        for locator_key in transition.locator_keys:
            _check_locator_conflict(
                locator_key,
                starts_by_locator.get(locator_key),
                start_secs,
                transition.start,
            )
            starts_by_locator[locator_key] = (start_secs, transition.start)
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


def _validate_chapter_locator(
    chapter: ChapterMarker,
    chapter_start: int,
    starts_by_locator: dict[str, tuple[int, str]],
) -> None:
    """Raise if the chapter's tei_locator does not align to its start time."""
    locator = typ.cast("str", chapter.tei_locator)
    segment_start_entry = starts_by_locator.get(locator)
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
    if chapter.tei_locator is not None:
        _validate_chapter_locator(chapter, chapter_start, starts_by_locator)
