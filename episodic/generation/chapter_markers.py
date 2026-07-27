"""Public chapter-marker generation API.

Implementation details live in focused chapter-marker modules for DTO
validation, segment alignment, LLM orchestration, and TEI enrichment. This
module preserves the original import path for callers.
"""

from episodic.generation.chapter_marker_generator import ChapterMarkersGenerator
from episodic.generation.chapter_marker_models import (
    ChapterMarker,
    ChapterMarkersGeneratorConfig,
    ChapterMarkersResponseFormatError,
    ChapterMarkersResult,
    _decode_object,
    _duration_to_seconds,
    _ensure_non_empty_field,
    _normalize_optional_string,
    _parse_chapter,
    _require_list,
    _require_non_empty_string,
    _require_optional_string,
)
from episodic.generation.chapter_marker_segments import (
    _MAX_SEGMENT_TRAVERSAL_DEPTH,
    _build_segment_start_lookups,
    _locator_keys_for_segment,
    _segment_transitions_from_value,
    _SegmentTransition,
    _transitions_from_dict,
    _transitions_from_sequence,
    _validate_chapter_aligns_to_segments,
    _validate_chapters_align_to_segments,
    _validate_segment_transition_starts,
)
from episodic.generation.chapter_marker_tei import (
    _build_chapters_div_payload,
    _build_item_payload,
    _iter_chapter_item_payloads,
    _prepare_empty_chapter_summaries_for_tei_rapporteur,
    enrich_tei_with_chapter_markers,
)

__all__ = [
    "_MAX_SEGMENT_TRAVERSAL_DEPTH",
    "ChapterMarker",
    "ChapterMarkersGenerator",
    "ChapterMarkersGeneratorConfig",
    "ChapterMarkersResponseFormatError",
    "ChapterMarkersResult",
    "_SegmentTransition",
    "_build_chapters_div_payload",
    "_build_item_payload",
    "_build_segment_start_lookups",
    "_decode_object",
    "_duration_to_seconds",
    "_ensure_non_empty_field",
    "_iter_chapter_item_payloads",
    "_locator_keys_for_segment",
    "_normalize_optional_string",
    "_parse_chapter",
    "_prepare_empty_chapter_summaries_for_tei_rapporteur",
    "_require_list",
    "_require_non_empty_string",
    "_require_optional_string",
    "_segment_transitions_from_value",
    "_transitions_from_dict",
    "_transitions_from_sequence",
    "_validate_chapter_aligns_to_segments",
    "_validate_chapters_align_to_segments",
    "_validate_segment_transition_starts",
    "enrich_tei_with_chapter_markers",
]
