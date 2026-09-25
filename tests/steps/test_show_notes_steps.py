"""Behavioural tests for the show notes generator."""

from __future__ import annotations

import asyncio  # noqa: TC003  # pytest-bdd evaluates step annotations.
import dataclasses as dc
import json
import typing as typ
from pathlib import Path  # noqa: TC003  # pytest-bdd evaluates step annotations.

import pytest
from pytest_bdd import given, scenario, then, when

from episodic.generation import (
    ShowNotesGenerator,
    ShowNotesGeneratorConfig,
    ShowNotesResult,
)
from episodic.llm import LLMProviderOperation, LLMTokenBudget
from episodic.llm.openai_adapter import (
    OpenAICompatibleLLMAdapter,
    OpenAICompatibleLLMConfig,
)
from tests.steps.vidaimock_harness import (
    start_vidaimock_process,
    terminate_process_gracefully,
)

if typ.TYPE_CHECKING:
    import collections.abc as cabc
    import subprocess  # noqa: S404 - types the local Vidai Mock test server child.

    from episodic.llm.ports import LLMPort, LLMRequest, LLMResponse


@dc.dataclass(slots=True)
class ShowNotesBDDContext:
    """Shared state between show notes BDD steps."""

    process: subprocess.Popen[str] | None = None
    base_url: str = ""
    script_tei_xml: str = ""
    template_structure: dict[str, object] | None = None
    result: ShowNotesResult | None = None
    request_payload: LLMRequest | None = None
    stderr_file: typ.TextIO | None = None


@dc.dataclass(slots=True)
class _RecordingLLMPort:
    """Capture the actual `LLMRequest` before delegating to the real adapter."""

    wrapped: LLMPort
    requests: list[LLMRequest] = dc.field(default_factory=list)

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Record and forward the request."""
        self.requests.append(request)
        return await self.wrapped.generate(request)


def _run_async_step(
    runner: asyncio.Runner,
    step_fn: cabc.Callable[[], cabc.Awaitable[None]],
) -> None:
    """Execute an async BDD step via the provided runner."""
    runner.run(step_fn())


@pytest.fixture
def show_notes_context() -> cabc.Iterator[ShowNotesBDDContext]:
    """Share state between show notes BDD steps and stop Vidai Mock afterward."""
    ctx = ShowNotesBDDContext()
    yield ctx
    if ctx.process is not None:
        terminate_process_gracefully(ctx.process, ctx.stderr_file)


@scenario(
    "../features/show_notes.feature",
    "Show notes generator extracts topics from a TEI script via a live Vidai "
    "Mock server",
)
def test_show_notes_behaviour() -> None:
    """Run the show notes behaviour scenario."""


def _build_assistant_content_literal() -> str:
    """Build the double-encoded assistant content JSON literal."""
    assistant_content = json.dumps({
        "entries": [
            {
                "topic": "Introduction",
                "summary": "Opening remarks and episode overview.",
                "timestamp": "PT0M30S",
            },
            {
                "topic": "Main Discussion",
                "summary": "In-depth analysis of the primary topic.",
                "timestamp": "PT5M15S",
            },
        ]
    })
    return json.dumps(assistant_content)


def _write_provider_config(provider_dir: Path) -> None:
    """Write the show-notes provider configuration to Vidai Mock."""
    provider_file = provider_dir / "openai.yaml"
    provider_file.write_text(
        "\n".join((
            'name: "show_notes"',
            'matcher: "/v1/chat/completions"',
            "request_mapping:",
            "  model: \"{{ json.model | default(value='gpt-4o-mini') }}\"",
            'response_template: "show_notes/response.json.j2"',
        ))
        + "\n",
        encoding="utf-8",
    )


def _write_response_template(
    template_dir: Path,
    assistant_content_literal: str,
) -> None:
    """Write the show-notes response template to Vidai Mock."""
    template_file = template_dir / "response.json.j2"
    template_file.write_text(
        f"""{{
  "id": "chatcmpl-{{{{ uuid() }}}}",
  "created": {{{{ timestamp() }}}},
  "object": "chat.completion",
  "model": "{{{{ model }}}}",
  "choices": [
    {{
      "index": 0,
      "message": {{
        "role": "assistant",
        "content": {assistant_content_literal}
      }},
      "finish_reason": "stop"
    }}
  ],
  "usage": {{
    "prompt_tokens": 50,
    "completion_tokens": 30,
    "total_tokens": 80
  }}
}}
""",
        encoding="utf-8",
    )


@given("a Vidai Mock show-notes server is running")
def vidaimock_server(
    show_notes_context: ShowNotesBDDContext,
    tmp_path: Path,
) -> None:
    """Start a local Vidai Mock instance with a show-notes-specific template."""
    provider_dir = tmp_path / "providers"
    template_dir = tmp_path / "templates" / "show_notes"
    provider_dir.mkdir(parents=True)
    template_dir.mkdir(parents=True)

    _write_provider_config(provider_dir)

    assistant_content_literal = _build_assistant_content_literal()
    _write_response_template(template_dir, assistant_content_literal)

    start_vidaimock_process(
        show_notes_context,
        tmp_path,
        label="the show-notes behavioural test",
    )


@given("a TEI script body is prepared for show-notes extraction")
def prepare_show_notes_request(show_notes_context: ShowNotesBDDContext) -> None:
    """Build a TEI script body for show-notes extraction."""
    # Simple TEI script with a couple of paragraphs
    show_notes_context.script_tei_xml = (
        '<TEI xmlns="http://www.tei-c.org/ns/1.0">'
        "<teiHeader><fileDesc><title>Episode 42</title></fileDesc></teiHeader>"
        "<text><body>"
        '<p xml:id="p1">Welcome to episode 42. Today we discuss the topic.</p>'
        '<p xml:id="p2">Let us dive deep into the analysis.</p>'
        "</body></text>"
        "</TEI>"
    )
    show_notes_context.template_structure = None


@when("the show-notes generator processes the script")
def run_show_notes_generation(
    _function_scoped_runner: asyncio.Runner,
    show_notes_context: ShowNotesBDDContext,
) -> None:
    """Call the show-notes generator with a live LLM adapter."""

    async def _generate_show_notes() -> None:
        async with OpenAICompatibleLLMAdapter(
            config=OpenAICompatibleLLMConfig(
                base_url=show_notes_context.base_url,
                api_key="test-key",
            ),
        ) as adapter:
            recording_port = _RecordingLLMPort(wrapped=adapter)

            config = ShowNotesGeneratorConfig(
                model="gpt-4o-mini",
                provider_operation=LLMProviderOperation.CHAT_COMPLETIONS,
                token_budget=LLMTokenBudget(
                    max_input_tokens=1000,
                    max_output_tokens=500,
                    max_total_tokens=1500,
                ),
            )

            generator = ShowNotesGenerator(llm=recording_port, config=config)

            result = await generator.generate(
                show_notes_context.script_tei_xml,
                template_structure=show_notes_context.template_structure,
            )

            show_notes_context.result = result
            show_notes_context.request_payload = recording_port.requests[0]

    _run_async_step(_function_scoped_runner, _generate_show_notes)


@then("the generator returns structured show-notes entries")
def assert_show_notes_result_structure(show_notes_context: ShowNotesBDDContext) -> None:
    """Verify the result contains structured entries with expected fields."""
    result = show_notes_context.result
    assert result is not None, "Expected a ShowNotesResult, got None."

    assert len(result.entries) == 2, (
        f"Expected 2 show-notes entries, got {len(result.entries)}."
    )

    first_entry = result.entries[0]
    assert first_entry.topic == "Introduction", "Expected values to match"
    assert "Opening remarks" in first_entry.summary, (
        "Expected collection to contain the value"
    )
    assert first_entry.timestamp == "PT0M30S", "Expected values to match"

    second_entry = result.entries[1]
    assert second_entry.topic == "Main Discussion", "Expected values to match"
    assert "In-depth analysis" in second_entry.summary, (
        "Expected collection to contain the value"
    )
    assert second_entry.timestamp == "PT5M15S", "Expected values to match"

    # Verify normalized usage metadata
    assert result.usage.input_tokens == 50, "Expected values to match"
    assert result.usage.output_tokens == 30, "Expected values to match"
    assert result.usage.total_tokens == 80, "Expected values to match"
    assert result.model == "gpt-4o-mini", "Expected values to match"
    assert result.finish_reason == "stop", "Expected values to match"


@then("the show-notes prompt includes the TEI script body")
def assert_prompt_contains_tei_script(show_notes_context: ShowNotesBDDContext) -> None:
    """Verify the actual outbound request includes the TEI script XML."""
    request = show_notes_context.request_payload
    assert request is not None, "Expected the adapter request to be captured."
    assert "Welcome to episode 42" in request.prompt, (
        "Expected the outbound prompt to contain script text from the TEI body."
    )
    assert "script_tei_xml" in request.prompt, (
        "Expected the outbound prompt to include the script_tei_xml key."
    )
