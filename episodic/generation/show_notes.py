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
import typing as typ

from episodic.llm import (
    LLMPort,
    LLMProviderOperation,
    LLMRequest,
    LLMResponse,
    LLMTokenBudget,
    LLMUsage,
)

type JsonMapping = dict[str, object]

_DEFAULT_SYSTEM_PROMPT = (
    "You are a podcast show-notes generator. Given a TEI P5 podcast script, "
    "extract the key topics discussed in the episode. For each topic, provide "
    "a short heading and a one-to-three sentence summary. If the script contains "
    "timing cues or segment markers, include an approximate timestamp as an ISO 8601 "
    'duration (e.g. PT5M30S). Return JSON only with key "entries". Each entry must '
    'include "topic" and "summary". Optional fields: "timestamp" and "tei_locator".'
)


def _ensure_non_empty_fields(instance: object, *field_names: str) -> None:
    """Reject blank or whitespace-only string fields on a dataclass instance."""
    for field_name in field_names:
        value = getattr(instance, field_name)
        if not isinstance(value, str) or value.strip() == "":
            msg = f"{field_name} must be non-empty."
            raise ValueError(msg)


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
    """

    entries: tuple[ShowNotesEntry, ...]
    usage: LLMUsage
    model: str = ""
    provider_response_id: str = ""
    finish_reason: str | None = None


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


def _decode_object(value: object, field_name: str) -> dict[str, object]:
    """Decode a JSON value as a dictionary or raise a format error."""
    if not isinstance(value, dict):
        msg = f"{field_name} must be an object."
        raise ShowNotesResponseFormatError(msg)
    return typ.cast("dict[str, object]", value)


def _require_non_empty_string(value: object, field_name: str) -> str:
    """Require a non-empty string value or raise a format error."""
    if not isinstance(value, str) or value.strip() == "":
        msg = f"{field_name} must be a non-empty string."
        raise ShowNotesResponseFormatError(msg)
    return value


def _require_list(value: object, field_name: str) -> list[object]:
    """Require a list value or raise a format error."""
    if not isinstance(value, list):
        msg = f"{field_name} must be a list."
        raise ShowNotesResponseFormatError(msg)
    return value


def _parse_entry(raw: dict[str, object]) -> ShowNotesEntry:
    """Parse a single show-notes entry from a JSON payload."""
    topic = _require_non_empty_string(raw.get("topic"), "topic")
    summary = _require_non_empty_string(raw.get("summary"), "summary")

    timestamp = raw.get("timestamp")
    if timestamp is not None and not isinstance(timestamp, str):
        msg = "timestamp must be a string or null."
        raise ShowNotesResponseFormatError(msg)

    tei_locator = raw.get("tei_locator")
    if tei_locator is not None and not isinstance(tei_locator, str):
        msg = "tei_locator must be a string or null."
        raise ShowNotesResponseFormatError(msg)

    return ShowNotesEntry(
        topic=topic,
        summary=summary,
        timestamp=timestamp if isinstance(timestamp, str) else None,
        tei_locator=tei_locator if isinstance(tei_locator, str) else None,
    )


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
            If the LLM response cannot be parsed into the expected format.
        LLMProviderResponseError
            If the LLM call fails with a non-retryable error.
        LLMTransientProviderError
            If the LLM call fails transiently after exhausting retries.
        """
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


def _xml_escape_attr(text: str) -> str:
    """Escape `&`, `<`, `>`, and `"` for use in an XML attribute value."""
    return (
        text
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _xml_escape_text(text: str) -> str:
    """Escape `&`, `<`, and `>` for use in XML text content."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _build_item_xml(entry: ShowNotesEntry) -> str:
    """Build one `<item>` XML fragment from a `ShowNotesEntry`."""
    attrs = []
    if entry.timestamp is not None:
        attrs.append(f'n="{_xml_escape_attr(entry.timestamp)}"')
    if entry.tei_locator is not None:
        attrs.append(f'corresp="{_xml_escape_attr(entry.tei_locator)}"')

    attr_str = " " + " ".join(attrs) if attrs else ""
    escaped_topic = _xml_escape_text(entry.topic)
    escaped_summary = _xml_escape_text(entry.summary)

    return f"""    <item{attr_str}>
      <label>{escaped_topic}</label>
      {escaped_summary}
    </item>"""


def _build_notes_div_xml(entries: list[ShowNotesEntry]) -> str:
    """Join the output of `_build_item_xml` for every entry and wrap in a div."""
    items_xml = [_build_item_xml(entry) for entry in entries]
    return f"""  <div type="notes">
    <list>
{chr(10).join(items_xml)}
    </list>
  </div>"""


def _insert_before_body_close(tei_xml: str, fragment: str) -> str:
    """Find the last `</body>` in `tei_xml` and insert `fragment` before it."""
    body_close_idx = tei_xml.rfind("</body>")
    if body_close_idx == -1:
        msg = "TEI document missing <body> element."
        raise ValueError(msg)
    return tei_xml[:body_close_idx] + fragment + "\n  " + tei_xml[body_close_idx:]


def enrich_tei_with_show_notes(
    tei_xml: str,
    result: ShowNotesResult,
) -> str:
    """Insert show-notes metadata into a TEI document body.

    Parameters
    ----------
    tei_xml : str
        TEI P5 XML document to enrich.
    result : ShowNotesResult
        Show-notes entries to insert.

    Returns
    -------
    str
        Enriched TEI XML as a string.

    Notes
    -----
    The enrichment creates a ``<div type="notes">`` element containing a
    ``<list>`` with ``<item>`` entries. Each item includes:

    - ``<label>``: topic text (required)
    - inline text: summary text (follows the label)
    - ``@n``: optional timestamp attribute
    - ``@corresp``: optional TEI locator attribute

    If the result has no entries, the original TEI is returned unchanged.

    This function uses XML string manipulation rather than the tei_rapporteur
    structured API because the API requires rebuilding the entire document
    from scratch. A future optimization could use the structured API once
    body modification helpers are available.
    """
    if not result.entries:
        return tei_xml
    div_xml = _build_notes_div_xml(list(result.entries))
    return _insert_before_body_close(tei_xml, div_xml)
