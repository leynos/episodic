"""Show-notes generator service tests."""

import json
import typing as typ

import pytest

from episodic.generation.show_notes import (
    ShowNotesGenerator,
    ShowNotesGeneratorConfig,
    ShowNotesResponseFormatError,
)
from tests import show_notes_support

_DEFAULT_SHOW_NOTES_PAYLOAD: typ.Final = {
    "entries": [{"topic": "Introduction", "summary": "Opening remarks"}]
}

_VALID_SHOW_NOTES_PAYLOADS: typ.Final = (
    pytest.param(_DEFAULT_SHOW_NOTES_PAYLOAD, id="single-entry"),
)


@pytest.fixture
def json_payload(request: pytest.FixtureRequest) -> str:
    """Return a serialized valid show-notes payload."""
    payload = getattr(request, "param", _DEFAULT_SHOW_NOTES_PAYLOAD)
    return json.dumps(payload)


@pytest.fixture
def xml_payload() -> str:
    """Return a minimal TEI script used by generation tests."""
    return "<TEI><text><body><p>Test script.</p></body></text></TEI>"


@pytest.fixture
def fake_llm(json_payload: str) -> show_notes_support.FakeLLMPort:
    """Return a fake LLM port configured with a valid response."""
    return show_notes_support.FakeLLMPort(
        show_notes_support.valid_llm_response(json_payload)
    )


@pytest.mark.parametrize("json_payload", _VALID_SHOW_NOTES_PAYLOADS, indirect=True)
@pytest.mark.asyncio
async def test_generate_calls_llm_and_returns_result(
    fake_llm: show_notes_support.FakeLLMPort,
    xml_payload: str,
) -> None:
    """The generate method calls the LLM and parses the response."""
    config = ShowNotesGeneratorConfig(model="test-model")
    generator = ShowNotesGenerator(llm=fake_llm, config=config)

    result = await generator.generate(xml_payload)

    assert len(fake_llm.requests) == 1, (
        f"expected exactly 1 LLM request but got {len(fake_llm.requests)}"
    )
    assert len(result.entries) == 1, (
        f"expected exactly 1 entry in result.entries but got {len(result.entries)}"
    )
    assert result.entries[0].topic == "Introduction", (
        "expected first entry topic to be 'Introduction' but was "
        f"{result.entries[0].topic!r}"
    )


@pytest.mark.parametrize("json_payload", _VALID_SHOW_NOTES_PAYLOADS, indirect=True)
@pytest.mark.asyncio
async def test_generate_sends_correct_llm_request_fields(
    fake_llm: show_notes_support.FakeLLMPort,
    xml_payload: str,
) -> None:
    """The outbound LLM request should honour the generator configuration."""
    config = ShowNotesGeneratorConfig(
        model="test-model",
        system_prompt="System prompt for tests.",
        token_budget=typ.cast("typ.Any", {"max_output_tokens": 128}),
    )
    generator = ShowNotesGenerator(llm=fake_llm, config=config)

    await generator.generate(xml_payload)

    assert len(fake_llm.requests) == 1, (
        f"expected exactly 1 LLM request but got {len(fake_llm.requests)}"
    )
    request = fake_llm.requests[0]
    assert request.model == config.model, (
        f"expected request.model {config.model!r}, got {request.model!r}"
    )
    assert request.system_prompt == config.system_prompt, (
        "expected request.system_prompt to match configured system prompt, "
        f"got {request.system_prompt!r}"
    )
    assert request.token_budget == config.token_budget, (
        f"expected token budget {config.token_budget!r}, got {request.token_budget!r}"
    )


@pytest.mark.asyncio
async def test_generate_raises_on_unparseable_response(xml_payload: str) -> None:
    """The generate method raises ShowNotesResponseFormatError for bad JSON."""
    fake_llm = show_notes_support.FakeLLMPort(
        show_notes_support.valid_llm_response("invalid json")
    )

    config = ShowNotesGeneratorConfig(model="test-model")
    generator = ShowNotesGenerator(llm=fake_llm, config=config)

    with pytest.raises(ShowNotesResponseFormatError, match="not valid JSON"):
        await generator.generate(xml_payload)
