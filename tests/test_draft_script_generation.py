"""Tests for single-pass draft script generation."""

import datetime as dt
import hashlib
import json
import typing as typ
import uuid

import pytest

from episodic.canonical.tei import parse_tei_header
from episodic.generation.draft_script import (
    DraftPresenterProfile,
    DraftScriptProviderResponseError,
    DraftScriptRequest,
    DraftScriptResponseFormatError,
    DraftScriptSource,
    DraftScriptTokenBudgetError,
    DraftScriptTransientProviderError,
    LLMDraftScriptGenerator,
    LLMDraftScriptGeneratorConfig,
)
from episodic.llm import (
    LLMProviderResponseError,
    LLMRequest,
    LLMResponse,
    LLMTokenBudgetExceededError,
    LLMTransientProviderError,
    LLMUsage,
)

if typ.TYPE_CHECKING:
    from syrupy.assertion import SnapshotAssertion


class FakeLLMPort:
    """Capture draft-generation requests and return a canned response."""

    def __init__(
        self,
        response: LLMResponse | None = None,
        error: Exception | None = None,
    ) -> None:
        self.response = response
        self.error = error
        self.requests: list[LLMRequest] = []

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Return the canned response or raise the configured error."""
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        if self.response is None:
            raise AssertionError
        return self.response


class SequentialDraftIds:
    """Deterministic TEI identifier factory for snapshots."""

    def __init__(self) -> None:
        self.counts: dict[str, int] = {}

    def __call__(self, prefix: str) -> str:
        """Return the next identifier for a TEI element prefix."""
        next_value = self.counts.get(prefix, 0) + 1
        self.counts[prefix] = next_value
        return f"{prefix}-{next_value}"


def _clock() -> dt.datetime:
    """Return the frozen draft-generation timestamp."""
    return dt.datetime(2026, 6, 24, 12, 0, tzinfo=dt.UTC)


def _valid_response() -> LLMResponse:
    """Return a valid draft script JSON response."""
    payload = {
        "title": "Bridgewater Futures",
        "turns": [
            {"speaker": "Host", "text": "Welcome to Bridgewater Futures."},
            {"speaker": "Guest", "text": "Thanks for inviting me."},
            {"text": "The conversation turns to implementation risks."},
        ],
    }
    return LLMResponse(
        text=json.dumps(payload),
        model="vidai-mock",
        provider_response_id="resp-draft-1",
        finish_reason="stop",
        usage=LLMUsage(input_tokens=100, output_tokens=50, total_tokens=150),
    )


def _request() -> DraftScriptRequest:
    """Return a representative draft-generation request."""
    return DraftScriptRequest(
        episode_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
        series_profile_id=uuid.UUID("00000000-0000-0000-0000-000000000002"),
        title="Bridgewater Futures",
        sources=(
            DraftScriptSource(
                source_id="source-1",
                source_type="research_brief",
                source_uri="https://example.test/source",
                content="Bridgewater is preparing a new product launch.",
                weight=1.0,
            ),
        ),
        presenter_profiles=(
            DraftPresenterProfile(
                display_name="Host",
                role="host",
                source_content="Experienced technical presenter.",
            ),
            DraftPresenterProfile(
                display_name="Guest",
                role="guest",
                source_content="Product lead for the launch.",
            ),
        ),
        clock=_clock,
        id_factory=SequentialDraftIds(),
    )


def test_draft_source_rejects_non_string_content() -> None:
    """Source validation distinguishes type errors from blank text."""
    with pytest.raises(TypeError, match="content must be a string"):
        DraftScriptSource(
            source_id="source-1",
            source_type="research_brief",
            source_uri="https://example.test/source",
            content=typ.cast("str", 1),
            weight=1.0,
        )


@pytest.mark.asyncio
async def test_draft_script_generator_emits_valid_stable_tei(
    snapshot: SnapshotAssertion,
) -> None:
    """LLM draft output should become validated deterministic TEI-P5."""
    fake_llm = FakeLLMPort(_valid_response())
    generator = LLMDraftScriptGenerator(
        llm=fake_llm,
        config=LLMDraftScriptGeneratorConfig(model="vidai-mock"),
    )

    result = await generator.generate(_request())

    parsed_title = parse_tei_header(result.tei_xml).title
    assert parsed_title == "Bridgewater Futures", (
        f"expected generated TEI title 'Bridgewater Futures', got {parsed_title!r}"
    )
    expected_hash = hashlib.sha256(result.tei_xml.encode()).hexdigest()
    assert result.content_hash == f"sha256:{expected_hash}", (
        f"expected generated TEI hash sha256:{expected_hash}, "
        f"got {result.content_hash!r}"
    )
    assert result.usage.total_tokens == 150, (
        f"expected 150 total tokens, got {result.usage.total_tokens}"
    )
    assert result.provider_response_id == "resp-draft-1", (
        "expected provider response 'resp-draft-1', "
        f"got {result.provider_response_id!r}"
    )
    assert fake_llm.requests[0].model == "vidai-mock", (
        f"expected model 'vidai-mock', got {fake_llm.requests[0].model!r}"
    )
    assert fake_llm.requests[0].system_prompt is not None, (
        "expected a system prompt, got None"
    )
    assert result.tei_xml == snapshot, "generated TEI must match the approved snapshot"


@pytest.mark.asyncio
async def test_draft_script_generator_serializes_deterministic_prompt() -> None:
    """Generator should send the complete deterministic draft context to the LLM."""
    fake_llm = FakeLLMPort(_valid_response())
    generator = LLMDraftScriptGenerator(
        llm=fake_llm,
        config=LLMDraftScriptGeneratorConfig(model="vidai-mock"),
    )

    await generator.generate(_request())

    expected_prompt = {
        "episode_id": "00000000-0000-0000-0000-000000000001",
        "presenter_profiles": [
            {
                "display_name": "Host",
                "role": "host",
                "source_content": "Experienced technical presenter.",
            },
            {
                "display_name": "Guest",
                "role": "guest",
                "source_content": "Product lead for the launch.",
            },
        ],
        "requested_at": "2026-06-24T12:00:00+00:00",
        "series_profile_id": "00000000-0000-0000-0000-000000000002",
        "sources": [
            {
                "content": "Bridgewater is preparing a new product launch.",
                "source_id": "source-1",
                "source_type": "research_brief",
                "source_uri": "https://example.test/source",
                "weight": 1.0,
            }
        ],
        "title": "Bridgewater Futures",
    }
    prompt = fake_llm.requests[0].prompt
    assert json.loads(prompt) == expected_prompt, (
        f"expected complete draft prompt payload, got {prompt!r}"
    )
    assert prompt == json.dumps(expected_prompt, indent=2, sort_keys=True), (
        "expected stable, sorted JSON prompt serialization"
    )


@pytest.mark.parametrize(
    ("llm_error", "expected_error"),
    [
        (LLMTokenBudgetExceededError(), DraftScriptTokenBudgetError),
        (LLMProviderResponseError(), DraftScriptProviderResponseError),
        (LLMTransientProviderError(), DraftScriptTransientProviderError),
    ],
)
@pytest.mark.asyncio
async def test_draft_script_generator_maps_llm_errors(
    llm_error: Exception,
    expected_error: type[Exception],
) -> None:
    """Provider failures should cross the generator boundary as draft errors."""
    generator = LLMDraftScriptGenerator(
        llm=FakeLLMPort(error=llm_error),
        config=LLMDraftScriptGeneratorConfig(model="vidai-mock"),
    )

    with pytest.raises(expected_error):
        await generator.generate(_request())


@pytest.mark.asyncio
async def test_draft_script_generator_rejects_malformed_completion() -> None:
    """Malformed LLM JSON should not reach TEI persistence."""
    generator = LLMDraftScriptGenerator(
        llm=FakeLLMPort(
            LLMResponse(
                text=json.dumps({
                    "title": "Bridgewater Futures",
                    "turns": [{"speaker": "Host"}],
                }),
                model="vidai-mock",
                provider_response_id="bad",
                finish_reason="stop",
                usage=LLMUsage(input_tokens=1, output_tokens=1, total_tokens=2),
            )
        ),
        config=LLMDraftScriptGeneratorConfig(model="vidai-mock"),
    )

    with pytest.raises(DraftScriptResponseFormatError, match="text"):
        await generator.generate(_request())
