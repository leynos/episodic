"""Define the port and implementation for one-pass draft script generation.

The immutable request and result types carry canonical source and presenter
context. ``DraftScriptGenerator`` is the public seam; its LLM implementation
maps provider failures, parses deterministic JSON, and emits TEI-P5 XML with
content hashes and usage metadata.

The launcher maps canonical documents and bindings into a request; generation
persistence stores the result on the canonical episode.
"""

import collections.abc as cabc
import dataclasses as dc
import json
import typing as typ

import tei_rapporteur as tei

from episodic.canonical.hashing import sha256_text
from episodic.generation.tei_payload import (
    require_mapping,
    require_non_empty_str_value,
    require_sequence,
)
from episodic.llm import (
    LLMPort,
    LLMProviderOperation,
    LLMProviderResponseError,
    LLMRequest,
    LLMResponse,
    LLMTokenBudget,
    LLMTokenBudgetExceededError,
    LLMTransientProviderError,
    LLMUsage,
    ProviderCallUsage,
)

if typ.TYPE_CHECKING:
    import datetime as dt
    import uuid

type JsonMapping = dict[str, object]
type DraftClock = cabc.Callable[[], dt.datetime]
type DraftIdFactory = cabc.Callable[[str], str]

_DEFAULT_SYSTEM_PROMPT = (
    "The assistant writes concise podcast draft scripts from supplied source "
    "material. Return JSON only with keys title and turns. Each turn must "
    "contain text and may contain speaker. Do not invent facts beyond the "
    "provided sources and presenter profiles."
)


class DraftScriptGenerationError(Exception):
    """Base class for draft script generation failures."""


class DraftScriptResponseFormatError(DraftScriptGenerationError, ValueError):
    """Raised when an LLM response does not match the draft schema."""


class DraftScriptTeiError(DraftScriptGenerationError, ValueError):
    """Raised when draft payloads cannot be emitted as valid TEI."""


class DraftScriptTokenBudgetError(DraftScriptGenerationError):
    """Raised when the LLM adapter rejects the draft request budget."""


class DraftScriptProviderResponseError(DraftScriptGenerationError):
    """Raised when the LLM provider returns a non-retryable response error."""


class DraftScriptTransientProviderError(DraftScriptGenerationError):
    """Raised when transient provider failures are exhausted."""


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


class DraftScriptGenerator(typ.Protocol):
    """Protocol implemented by one-pass draft generators."""

    async def generate(self, request: DraftScriptRequest) -> DraftScriptResult:
        """Generate one draft script from canonical generation context.

        Parameters
        ----------
        request
            Immutable canonical generation context.

        Returns
        -------
        DraftScriptResult
            Generated TEI-P5 XML, hash, and provider metadata.

        Raises
        ------
        DraftScriptGenerationError
            If generation cannot produce a valid draft.
        """
        raise NotImplementedError


@dc.dataclass(frozen=True, slots=True)
class _ParsedDraft:
    """Represent a parsed draft title and its ordered turns."""

    title: str
    turns: tuple[DraftTurn, ...]


@dc.dataclass(frozen=True, slots=True)
class LLMDraftScriptGenerator(DraftScriptGenerator):
    """Generate draft TEI scripts through an LLM port and its configuration."""

    llm: LLMPort
    config: LLMDraftScriptGeneratorConfig

    async def generate(self, request: DraftScriptRequest) -> DraftScriptResult:
        """Generate and validate one TEI-P5 draft script.

        Parameters
        ----------
        request
            Canonical context used to build the deterministic prompt.

        Returns
        -------
        DraftScriptResult
            Validated TEI-P5 XML, hash, usage, and provider metadata.

        Raises
        ------
        DraftScriptTokenBudgetError
            If the LLM adapter rejects the requested token budget.
        DraftScriptProviderResponseError
            If the provider returns a non-retryable response error.
        DraftScriptTransientProviderError
            If the provider reports a transient failure.
        DraftScriptResponseFormatError
            If the provider response is not the expected JSON draft.
        DraftScriptTeiError
            If the parsed draft cannot be emitted as valid TEI-P5.

        Notes
        -----
        Provider errors are translated before parsing and TEI emission.
        """  # noqa: DOC502  # Parsing and TEI helpers raise these documented exceptions.
        llm_request = LLMRequest(
            model=self.config.model,
            prompt=_build_prompt(request),
            system_prompt=self.config.system_prompt,
            provider_operation=self.config.provider_operation,
            token_budget=self.config.token_budget,
        )
        try:
            response = await self.llm.generate(llm_request)
        except LLMTokenBudgetExceededError as exc:
            raise DraftScriptTokenBudgetError(str(exc)) from exc
        except LLMProviderResponseError as exc:
            raise DraftScriptProviderResponseError(str(exc)) from exc
        except LLMTransientProviderError as exc:
            raise DraftScriptTransientProviderError(str(exc)) from exc

        _require_response_size(response.text, self.config.max_response_bytes)
        parsed = _parse_response(response)
        tei_xml = _emit_tei(parsed, request.id_factory)
        return DraftScriptResult(
            tei_xml=tei_xml,
            content_hash=sha256_text(tei_xml),
            usage=response.usage,
            model=response.model,
            provider_response_id=response.provider_response_id,
            finish_reason=response.finish_reason,
            provider_call_usage=response.provider_call_usage,
        )


def _require_non_empty_text(value: str, field_name: str) -> None:
    """Reject blank strings."""
    if not isinstance(value, str):
        msg = f"{field_name} must be a string."
        raise TypeError(msg)
    if value.strip() == "":
        msg = f"{field_name} must be a non-empty string."
        raise ValueError(msg)


def _build_prompt(request: DraftScriptRequest) -> str:
    """Build a deterministic JSON prompt payload."""
    payload: JsonMapping = {
        "episode_id": str(request.episode_id),
        "series_profile_id": str(request.series_profile_id),
        "title": request.title,
        "requested_at": request.clock().isoformat(),
        "sources": [dc.asdict(source) for source in request.sources],
        "presenter_profiles": [
            dc.asdict(profile) for profile in request.presenter_profiles
        ],
    }
    return json.dumps(payload, indent=2, sort_keys=True)


def _require_response_size(response_text: str, maximum_bytes: int) -> None:
    """Reject provider responses that exceed the configured byte limit."""
    if len(response_text.encode("utf-8")) > maximum_bytes:
        msg = "LLM response exceeds the configured maximum size."
        raise DraftScriptResponseFormatError(msg)


def _parse_response(response: LLMResponse) -> _ParsedDraft:
    """Parse and validate the LLM response JSON."""
    try:
        payload = json.loads(response.text)
    except json.JSONDecodeError as exc:
        msg = "LLM response is not valid JSON."
        raise DraftScriptResponseFormatError(msg) from exc

    payload_dict = require_mapping(
        payload,
        "response",
        error_cls=DraftScriptResponseFormatError,
    )
    title = require_non_empty_str_value(
        payload_dict.get("title"),
        "title",
        error_cls=DraftScriptResponseFormatError,
    ).strip()
    raw_turns = require_sequence(
        payload_dict.get("turns"),
        "turns",
        error_cls=DraftScriptResponseFormatError,
    )
    turns = tuple(_parse_turn(raw_turn) for raw_turn in raw_turns)
    if len(turns) == 0:
        msg = "turns must contain at least one turn."
        raise DraftScriptResponseFormatError(msg)
    return _ParsedDraft(title=title, turns=turns)


def _parse_turn(raw_turn: object) -> DraftTurn:
    """Parse one generated turn."""
    turn = require_mapping(
        raw_turn,
        "turn",
        error_cls=DraftScriptResponseFormatError,
    )
    text = require_non_empty_str_value(
        turn.get("text"),
        "text",
        error_cls=DraftScriptResponseFormatError,
    ).strip()
    speaker = _optional_non_empty_string(turn.get("speaker"), "speaker")
    return DraftTurn(text=text, speaker=speaker)


def _optional_non_empty_string(value: object, field_name: str) -> str | None:
    """Return an optional stripped string or raise a format error."""
    if value is None:
        return None
    if not isinstance(value, str):
        msg = f"{field_name} must be a string or null."
        raise DraftScriptResponseFormatError(msg)
    stripped = value.strip()
    return stripped or None


def _emit_tei(parsed: _ParsedDraft, id_factory: DraftIdFactory) -> str:
    """Emit validated TEI XML from a parsed draft."""
    payload: JsonMapping = {
        "header": {"file_desc": {"title": parsed.title}},
        "text": {
            "body": {
                "blocks": [_turn_to_block(turn, id_factory) for turn in parsed.turns]
            }
        },
    }
    try:
        document = tei.from_dict(payload)
        document.validate()
        return tei.emit_xml(document)
    except (TypeError, ValueError) as exc:
        raise DraftScriptTeiError(str(exc)) from exc


def _turn_to_block(turn: DraftTurn, id_factory: DraftIdFactory) -> JsonMapping:
    """Convert one generated turn to a `tei_rapporteur` body block."""
    content = [{"type": "text", "value": turn.text}]
    if turn.speaker is None:
        return {
            "type": "paragraph",
            "xml_id": id_factory("p"),
            "content": content,
        }
    return {
        "type": "utterance",
        "speaker": turn.speaker,
        "xml_id": id_factory("u"),
        "content": content,
    }
