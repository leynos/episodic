"""Public chapter-marker generation API.

Implementation details live in focused chapter-marker modules for DTO
validation, segment alignment, LLM orchestration, and TEI enrichment. This
module preserves the original import path for callers.
"""

import episodic.generation.chapter_marker_models as _models
import episodic.generation.chapter_marker_segments as _segments
import episodic.generation.chapter_marker_tei as _tei
from episodic.generation.chapter_marker_generator import ChapterMarkersGenerator

ChapterMarker = _models.ChapterMarker
ChapterMarkersGeneratorConfig = _models.ChapterMarkersGeneratorConfig
ChapterMarkersResponseFormatError = _models.ChapterMarkersResponseFormatError
ChapterMarkersResult = _models.ChapterMarkersResult
_decode_object = _models._decode_object
_duration_to_seconds = _models._duration_to_seconds
_ensure_non_empty_field = _models._ensure_non_empty_field
_normalize_optional_string = _models._normalize_optional_string
_parse_chapter = _models._parse_chapter
_require_list = _models._require_list
_require_non_empty_string = _models._require_non_empty_string
_require_optional_string = _models._require_optional_string

_MAX_SEGMENT_TRAVERSAL_DEPTH = _segments._MAX_SEGMENT_TRAVERSAL_DEPTH
_SegmentTransition = _segments._SegmentTransition
_build_segment_start_lookups = _segments._build_segment_start_lookups
_locator_keys_for_segment = _segments._locator_keys_for_segment
_segment_transitions_from_value = _segments._segment_transitions_from_value
_transitions_from_dict = _segments._transitions_from_dict
_transitions_from_sequence = _segments._transitions_from_sequence
_validate_chapter_aligns_to_segments = _segments._validate_chapter_aligns_to_segments
_validate_chapters_align_to_segments = _segments._validate_chapters_align_to_segments
_validate_segment_transition_starts = _segments._validate_segment_transition_starts

_build_chapters_div_payload = _tei._build_chapters_div_payload
_build_item_payload = _tei._build_item_payload
_iter_chapter_item_payloads = _tei._iter_chapter_item_payloads
_prepare_empty_chapter_summaries_for_tei_rapporteur = (
    _tei._prepare_empty_chapter_summaries_for_tei_rapporteur
)
enrich_tei_with_chapter_markers = _tei.enrich_tei_with_chapter_markers

__all__ = [
    "ChapterMarker",
    "ChapterMarkersGenerator",
    "ChapterMarkersGeneratorConfig",
    "ChapterMarkersResponseFormatError",
    "ChapterMarkersResult",
    "enrich_tei_with_chapter_markers",
]
