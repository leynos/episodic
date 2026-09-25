"""Immutable request, result, and configuration types for draft generation.

``DraftScriptSource`` and ``DraftPresenterProfile`` carry the canonical
source and presenter context bundled into a ``DraftScriptRequest``.
``DraftTurn`` and ``DraftScriptResult`` carry the generated output, and
``LLMDraftScriptGeneratorConfig`` configures the LLM-backed implementation
in ``episodic.generation.draft_script``.
"""

import collections.abc as cabc
import dataclasses as dc
import typing as typ

from episodic.llm import (
    LLMProviderOperation,
    LLMTokenBudget,
    LLMUsage,
    ProviderCallUsage,
)

if typ.TYPE_CHECKING:
    import datetime as dt
    import uuid

type DraftClock = cabc.Callable[[], dt.datetime]
type DraftIdFactory = cabc.Callable[[str], str]

_DEFAULT_SYSTEM_PROMPT = (
    "The assistant writes concise podcast draft scripts from supplied source "
    "material. Return JSON only with keys title and turns. Each turn must "
    "contain text and may contain speaker. Do not invent facts beyond the "
    "provided sources and presenter profiles."
)


def _require_non_empty_text(value: str, field_name: str) -> None:
    """Reject blank strings."""
    if not isinstance(value, str):
        msg = f"{field_name} must be a string."
        raise TypeError(msg)
    if value.strip() == "":
        msg = f"{field_name} must be a non-empty string."
        raise ValueError(msg)


@dc.dataclass(frozen=True, slots=True)
class DraftScriptSource:
    """Source identity, provenance, prompt text, and relative weight."""

    source_id: str
    source_type: str
    source_uri: str
    content: str
    weight: float

    def __post_init__(self) -> None:
        """Validate source fields."""
        _require_non_empty_text(self.source_id, "source_id")
        _require_non_empty_text(self.source_type, "source_type")
        _require_non_empty_text(self.source_uri, "source_uri")
        _require_non_empty_text(self.content, "content")
        if not 0 <= self.weight <= 1:
            msg = "weight must be between 0 and 1."
            raise ValueError(msg)


@dc.dataclass(frozen=True, slots=True)
class DraftPresenterProfile:
    """Presenter identity, role, and reference text for generation context."""

    display_name: str
    role: str
    source_content: str

    def __post_init__(self) -> None:
        """Validate presenter profile fields."""
        _require_non_empty_text(self.display_name, "display_name")
        _require_non_empty_text(self.role, "role")
        _require_non_empty_text(self.source_content, "source_content")


@dc.dataclass(frozen=True, slots=True)
class DraftScriptRequest:
    """Immutable input required to generate one draft TEI script.

    Attributes
    ----------
    episode_id, series_profile_id, title
        Canonical context and non-empty working title.
    sources, presenter_profiles
        Required sources and optional presenter context.
    clock, id_factory
        Deterministic timestamp and TEI-ID seams.
    """

    episode_id: uuid.UUID
    series_profile_id: uuid.UUID
    title: str
    sources: tuple[DraftScriptSource, ...]
    presenter_profiles: tuple[DraftPresenterProfile, ...]
    clock: DraftClock
    id_factory: DraftIdFactory

    def __post_init__(self) -> None:
        """Validate draft request fields."""
        _require_non_empty_text(self.title, "title")
        if len(self.sources) == 0:
            msg = "sources must contain at least one source."
            raise ValueError(msg)


@dc.dataclass(frozen=True, slots=True)
class DraftTurn:
    """One ordered generated turn with text and an optional speaker."""

    text: str
    speaker: str | None = None

    def __post_init__(self) -> None:
        """Validate turn text and speaker."""
        _require_non_empty_text(self.text, "text")
        if self.speaker is not None:
            _require_non_empty_text(self.speaker, "speaker")


@dc.dataclass(frozen=True, slots=True)
class DraftScriptResult:
    """Generated draft TEI and the provider metadata needed downstream.

    Attributes
    ----------
    tei_xml, content_hash, usage
        TEI-P5 output, canonical hash, and normalised usage.
    model, provider_response_id, finish_reason, provider_call_usage
        Provider metadata for lifecycle and cost recording.
    """

    tei_xml: str
    content_hash: str
    usage: LLMUsage
    model: str
    provider_response_id: str
    finish_reason: str | None
    provider_call_usage: ProviderCallUsage | None = None


@dc.dataclass(frozen=True, slots=True)
class LLMDraftScriptGeneratorConfig:
    """Configuration for one-pass draft-script generation.

    Attributes
    ----------
    model : str
        Provider model identifier.
    provider_operation : LLMProviderOperation | str
        Provider operation shape used for the request.
    token_budget : LLMTokenBudget | None
        Token budget constraints for the request, or ``None`` for no token
        budget.
    system_prompt : str
        System prompt sent with the draft-generation request.
    max_response_bytes : int
        Positive maximum UTF-8 response size in bytes. The cap is checked
        before the generated JSON is parsed.
    """

    model: str
    provider_operation: LLMProviderOperation | str = (
        LLMProviderOperation.CHAT_COMPLETIONS
    )
    token_budget: LLMTokenBudget | None = None
    system_prompt: str = _DEFAULT_SYSTEM_PROMPT
    max_response_bytes: int = 1_048_576

    def __post_init__(self) -> None:
        """Reject non-positive response-size limits."""
        if self.max_response_bytes < 1:
            msg = "max_response_bytes must be positive."
            raise ValueError(msg)
