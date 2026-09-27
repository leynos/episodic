"""Show-notes data contracts and their field validators.

This module holds the value objects exchanged by the show-notes generator
(``ShowNotesEntry``, ``ShowNotesResult``, ``ShowNotesGeneratorConfig``) along
with the small validation helpers their ``__post_init__`` hooks call. It is
split out of :mod:`episodic.generation.show_notes` so that module stays under
the project's line-count limit; import the public names from
:mod:`episodic.generation.show_notes` rather than from here.
"""

import dataclasses as dc
import re

from episodic.llm import (
    LLMProviderOperation,
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
