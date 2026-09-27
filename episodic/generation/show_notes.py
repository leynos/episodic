"""Show notes generation from template expansions.

This module implements a show-notes generator that extracts key topics and
timestamps from TEI P5 podcast scripts using an LLM, then formats the results
as structured metadata within a canonical TEI body.

Main entry points:

- ``ShowNotesGenerator``: The primary generator class that orchestrates
  LLM-based show-notes extraction. Call ``await generator.generate(script_xml)``
  to analyze a script and receive structured show-notes entries.

- ``ShowNotesEntry``: A single show-note item with topic, summary, optional
  timestamp (ISO 8601 duration), and optional TEI locator.

- ``ShowNotesResult``: Output contract providing structured entries, LLM usage
  metadata, and response metadata.

- ``enrich_tei_with_show_notes(tei_xml, result)``: TEI body enrichment helper
  that inserts a ``<div type="notes">`` element containing structured show-notes
  metadata into a TEI document.

Typical usage::

    config = ShowNotesGeneratorConfig(
        model="gpt-4o-mini",
        provider_operation=LLMProviderOperation.CHAT_COMPLETIONS,
        token_budget=LLMTokenBudget(
            max_input_tokens=1000,
            max_output_tokens=500,
            max_total_tokens=1500,
        ),
    )
    generator = ShowNotesGenerator(llm=adapter, config=config)

    script_xml = "<TEI>...</TEI>"
    result = await generator.generate(script_xml)

    enriched_xml = enrich_tei_with_show_notes(script_xml, result)

Constraints:

- ``topic`` and ``summary`` fields must be non-empty strings.
- ``timestamp`` field, when provided, should be an ISO 8601 duration (e.g.,
  ``PT5M30S`` for five minutes and thirty seconds).
- LLM responses must conform to the expected JSON schema or
  ``ShowNotesResponseFormatError`` is raised.

The data contracts, JSON-response parsing helpers, and TEI enrichment helper
live in sibling modules (``show_notes_models``, ``show_notes_parsing``, and
``show_notes_enrichment`` respectively) to keep this module under the
project's line-count limit; they are re-exported here so callers keep
importing from this module.
"""

import dataclasses as dc
import json

from episodic.generation.show_notes_enrichment import enrich_tei_with_show_notes
from episodic.generation.show_notes_models import (
    JsonMapping,
    ShowNotesEntry,
    ShowNotesGeneratorConfig,
    ShowNotesResult,
)
from episodic.generation.show_notes_parsing import (
    ShowNotesResponseFormatError,
    _decode_object,
    _parse_entry,
    _require_list,
)
from episodic.llm import LLMPort, LLMRequest, LLMResponse

__all__ = [
    "ShowNotesEntry",
    "ShowNotesGenerator",
    "ShowNotesGeneratorConfig",
    "ShowNotesResponseFormatError",
    "ShowNotesResult",
    "enrich_tei_with_show_notes",
]


@dc.dataclass(slots=True)
class ShowNotesGenerator:
    """Show-notes generator service backed by an LLM.

    Attributes
    ----------
    llm : LLMPort
        LLM adapter for generating show-notes content.
    config : ShowNotesGeneratorConfig
        Generator configuration including model, operation, and token budget.
    """

    llm: LLMPort
    config: ShowNotesGeneratorConfig

    @staticmethod
    def build_prompt(
        script_tei_xml: str,
        *,
        template_structure: JsonMapping | None = None,
    ) -> str:
        """Build the user prompt for show-notes extraction.

        Parameters
        ----------
        script_tei_xml : str
            TEI P5 XML script body to extract show notes from.
        template_structure : JsonMapping | None
            Optional template structure metadata to guide extraction.

        Returns
        -------
        str
            JSON-formatted prompt for the LLM.
        """
        prompt_payload: JsonMapping = {"script_tei_xml": script_tei_xml}
        if template_structure is not None:
            prompt_payload["template_structure"] = template_structure

        return json.dumps(prompt_payload, indent=2)

    @staticmethod
    def _result_from_response(response: LLMResponse) -> ShowNotesResult:
        """Parse an LLM response into a ShowNotesResult.

        Parameters
        ----------
        response : LLMResponse
            LLM response containing JSON-formatted show-notes entries.

        Returns
        -------
        ShowNotesResult
            Parsed show-notes result with validated entries.

        Raises
        ------
        ShowNotesResponseFormatError
            If the response text cannot be parsed as JSON or does not conform
            to the expected schema.
        """
        try:
            payload = json.loads(response.text)
        except json.JSONDecodeError as exc:
            msg = "LLM response is not valid JSON."
            raise ShowNotesResponseFormatError(msg) from exc

        payload_dict = _decode_object(payload, "response")
        entries_raw = _require_list(payload_dict.get("entries"), "entries")

        entries = tuple(_parse_entry(_decode_object(e, "entry")) for e in entries_raw)

        return ShowNotesResult(
            entries=entries,
            usage=response.usage,
            model=response.model,
            provider_response_id=response.provider_response_id,
            finish_reason=response.finish_reason,
            provider_call_usage=response.provider_call_usage,
        )

    async def generate(
        self,
        script_tei_xml: str,
        *,
        template_structure: JsonMapping | None = None,
    ) -> ShowNotesResult:
        """Generate show notes from a TEI script body.

        Parameters
        ----------
        script_tei_xml : str
            TEI P5 XML script body to extract show notes from.
        template_structure : JsonMapping | None
            Optional template structure metadata to guide extraction.

        Returns
        -------
        ShowNotesResult
            Structured show-notes entries with LLM usage metadata.

        Raises
        ------
        ShowNotesResponseFormatError
            If the provider response cannot be parsed into the expected format.
        LLMProviderResponseError
            If the provider returns a non-retryable error response.
        LLMTransientProviderError
            If transient provider failures exhaust all retry attempts.
        LLMTokenBudgetExceededError
            If preflight validation or provider-reported usage exceeds the
            request token budget.
        """  # noqa: DOC502  # Documents exceptions propagated by collaborators.
        prompt = self.build_prompt(
            script_tei_xml, template_structure=template_structure
        )

        request = LLMRequest(
            model=self.config.model,
            prompt=prompt,
            system_prompt=self.config.system_prompt,
            provider_operation=self.config.provider_operation,
            token_budget=self.config.token_budget,
        )

        response = await self.llm.generate(request)
        return self._result_from_response(response)
