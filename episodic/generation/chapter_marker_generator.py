"""LLM orchestration for chapter-marker generation."""

import dataclasses as dc
import json

from episodic.generation.chapter_marker_common import JsonMapping, logger
from episodic.generation.chapter_marker_models import (
    ChapterMarkersGeneratorConfig,
    ChapterMarkersResponseFormatError,
    ChapterMarkersResult,
    _decode_object,
    _parse_chapter,
    _require_list,
)
from episodic.generation.chapter_marker_segments import (
    _validate_chapters_align_to_segments,
)
from episodic.llm import LLMPort, LLMRequest, LLMResponse
from episodic.logging import log_info


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
        try:
            _validate_chapters_align_to_segments(result, segment_structure)
        except ChapterMarkersResponseFormatError:
            logger.warning("chapter_markers_alignment_validation_failed")
            raise
        return result
