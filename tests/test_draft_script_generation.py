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

    assert parse_tei_header(result.tei_xml).title == "Bridgewater Futures"
    assert '<u xml:id="u-1" who="Host">Welcome' in result.tei_xml
    assert '<u xml:id="u-2" who="Guest">Thanks' in result.tei_xml
    assert '<p xml:id="p-1">The conversation' in result.tei_xml
    expected_hash = hashlib.sha256(result.tei_xml.encode()).hexdigest()
    assert result.content_hash == f"sha256:{expected_hash}"
    assert result.usage.total_tokens == 150
    assert result.provider_response_id == "resp-draft-1"
    assert fake_llm.requests[0].model == "vidai-mock"
    assert fake_llm.requests[0].system_prompt is not None
    assert result.tei_xml == snapshot


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
