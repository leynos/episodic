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
"""

import dataclasses as dc
import json
import re

from episodic.llm import (
    LLMPort,
    LLMProviderOperation,
    LLMRequest,
    LLMResponse,
    LLMTokenBudget,
    LLMUsage,
    ProviderCallUsage,
)

type JsonMapping = dict[str, object]

_DEFAULT_SYSTEM_PROMPT = (
    "The assistant acts as a podcast show-notes generator. Given a TEI P5 "
    "podcast script, "
    "extract the key topics discussed in the episode. For each topic, provide "
    "a short heading and a one-to-three sentence summary. If the script contains "
    "timing cues or segment markers, include an approximate timestamp as an ISO 8601 "
    'duration (e.g. PT5M30S). Return JSON only with key "entries". Each entry must '
    'include "topic" and "summary". Optional fields: "timestamp" and "tei_locator".'
)

_ISO_8601_DURATION_PATTERN = re.compile(
    r"^P(?=.*\d(?:\.\d+)?[YMWDHS])"
    r"(?:\d+(?:\.\d+)?W|"
    r"(?:\d+(?:\.\d+)?Y)?"
    r"(?:\d+(?:\.\d+)?M)?"
    r"(?:\d+(?:\.\d+)?D)?"
    r"(?:T"
    r"(?:\d+(?:\.\d+)?H)?"
    r"(?:\d+(?:\.\d+)?M)?"
    r"(?:\d+(?:\.\d+)?S)?"
    r")?"
    r")$"
)


def _ensure_non_empty_fields(instance: object, *field_names: str) -> None:
    """Reject blank or whitespace-only string fields on a dataclass instance."""
    for field_name in field_names:
        value = getattr(instance, field_name)
        if not isinstance(value, str) or not value.strip():
            msg = f"{field_name} must be non-empty."
            raise ValueError(msg)


def _ensure_optional_iso8601_duration(timestamp: str | None) -> None:
    """Reject timestamp strings that are not ISO 8601 durations."""
    if timestamp is None:
        return
    if _ISO_8601_DURATION_PATTERN.fullmatch(timestamp) is None:
        msg = "timestamp must be an ISO 8601 duration."
        raise ValueError(msg)


def _normalize_optional_tei_locator(tei_locator: str | None) -> str | None:
    """Normalize blank TEI locators to None and strip surrounding whitespace."""
    if tei_locator is None:
        return None
    normalized = tei_locator.strip()
    if not normalized:
        return None
    return normalized


@dc.dataclass(frozen=True, slots=True)
class ShowNotesEntry:
    """A single show-note item extracted from a podcast script.

    Attributes
    ----------
    topic : str
        Short heading for the show-note item (non-empty).
    summary : str
        One-to-three sentence description (non-empty).
    timestamp : str | None
        Optional ISO 8601 duration string (e.g., ``PT5M30S`` for five minutes
        and thirty seconds).
    tei_locator : str | None
        Optional XPath or element identifier pointing into the source script
        TEI body.
    """

    topic: str
    summary: str
    timestamp: str | None = None
    tei_locator: str | None = None

    def __post_init__(self) -> None:
        """Reject blank topic and summary fields."""
        _ensure_non_empty_fields(self, "topic", "summary")
        _ensure_optional_iso8601_duration(self.timestamp)
        object.__setattr__(
            self,
            "tei_locator",
            _normalize_optional_tei_locator(self.tei_locator),
        )


@dc.dataclass(frozen=True, slots=True)
class ShowNotesResult:
    """Show-notes generation result with structured entries and metadata.

    Attributes
    ----------
    entries : tuple[ShowNotesEntry, ...]
        Structured show-notes entries extracted from the script.
    usage : LLMUsage
        Normalized token usage metadata for accounting.
    model : str
        Provider model identifier used for generation.
    provider_response_id : str
        Provider-native response identifier.
    finish_reason : str | None
        Completion stop reason when provided by the vendor.
    provider_call_usage : ProviderCallUsage | None
        Provider-specific usage metrics for cost accounting.
    """

    entries: tuple[ShowNotesEntry, ...]
    usage: LLMUsage
    model: str = ""
    provider_response_id: str = ""
    finish_reason: str | None = None
    provider_call_usage: ProviderCallUsage | None = None


@dc.dataclass(frozen=True, slots=True)
class ShowNotesGeneratorConfig:
    """Configuration for the show-notes generator service.

    Attributes
    ----------
    model : str
        Provider model identifier (e.g., ``gpt-4o-mini``).
    provider_operation : LLMProviderOperation | str
        Provider operation shape (default: ``CHAT_COMPLETIONS``).
    token_budget : LLMTokenBudget | None
        Token budget constraints, or ``None`` for no limit.
    system_prompt : str
        System prompt instructing the LLM on show-notes extraction.
    """

    model: str
    provider_operation: LLMProviderOperation | str = (
        LLMProviderOperation.CHAT_COMPLETIONS
    )
    token_budget: LLMTokenBudget | None = None
    system_prompt: str = _DEFAULT_SYSTEM_PROMPT


class ShowNotesResponseFormatError(ValueError):
    """Raised when the LLM response cannot be parsed into ShowNotesResult."""


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

        """
        from episodic.generation.show_notes_parsing import parse_show_notes_response

        return parse_show_notes_response(response)

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


def enrich_tei_with_show_notes(tei_xml: str, result: ShowNotesResult) -> str:
    """Insert show-notes metadata into a TEI document.

    Returns
    -------
    str
        Enriched TEI XML, or the original document for an empty result.
    """
    from episodic.generation.show_notes_tei import enrich_tei_with_show_notes as enrich

    return enrich(tei_xml, result)
