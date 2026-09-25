"""Behavioural tests for live chapter-marker inference.

This module verifies the adapter-facing path that unit tests intentionally
avoid. It starts Vidai Mock with an OpenAI-compatible chat-completion template,
uses the real `OpenAICompatibleLLMAdapter`, records the outbound `LLMRequest`,
and drives `ChapterMarkersGenerator` through pytest-bdd steps.

The scenario proves the component relationships across the generation service,
LLM port, OpenAI-compatible adapter, Vidai Mock test server, and TEI enrichment
helper. The local server is process-scoped to the fixture and cleaned up
through the shared termination helper.
"""

from __future__ import annotations

import asyncio
import dataclasses as dc
import json
import typing as typ
from pathlib import Path  # noqa: TC003  # pytest-bdd evaluates step annotations.

import pytest
from pytest_bdd import given, scenario, then, when

from episodic.generation import (
    ChapterMarkersGenerator,
    ChapterMarkersGeneratorConfig,
    ChapterMarkersResult,
    enrich_tei_with_chapter_markers,
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
class ChapterMarkersBDDContext:
    """Shared state between chapter-marker BDD steps."""

    process: subprocess.Popen[str] | None = None
    base_url: str = ""
    script_tei_xml: str = ""
    segment_structure: dict[str, object] | None = None
    result: ChapterMarkersResult | None = None
    request_payload: LLMRequest | None = None
    enriched_tei_xml: str = ""
    stderr_file: typ.TextIO | None = None


@dc.dataclass(slots=True)
class _RecordingLLMPort:
    """Capture the actual `LLMRequest` before delegating to the real adapter."""

    wrapped: LLMPort
    requests: list[LLMRequest] = dc.field(default_factory=list)
    lock: asyncio.Lock = dc.field(default_factory=asyncio.Lock)

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Record and forward the request."""
        async with self.lock:
            self.requests.append(request)
        return await self.wrapped.generate(request)


def _run_async_step(
    step_fn: cabc.Callable[[], cabc.Coroutine[object, object, None]],
) -> None:
    """Execute an async BDD step through the public asyncio runner API."""
    asyncio.run(step_fn())


@pytest.fixture
def chapter_markers_context() -> cabc.Iterator[ChapterMarkersBDDContext]:
    """Share state between chapter-marker steps and stop Vidai Mock afterward."""
    ctx = ChapterMarkersBDDContext()
    yield ctx
    if ctx.process is not None:
        terminate_process_gracefully(ctx.process, ctx.stderr_file)


@scenario(
    "../features/chapter_markers.feature",
    "Chapter marker generator creates chapters from a TEI script via a live "
    "Vidai Mock server",
)
def test_chapter_markers_behaviour() -> None:
    """Run the chapter-marker behaviour scenario."""


def _build_assistant_content_literal() -> str:
    """Build the double-encoded assistant content JSON literal."""
    assistant_content = json.dumps({
        "chapters": [
            {
                "title": "Introduction",
                "start": "PT0S",
                "summary": "Opening context and episode setup.",
                "tei_locator": "#seg-intro",
            },
            {
                "title": "Main discussion",
                "start": "PT5M30S",
                "summary": "The hosts move into the central discussion.",
                "tei_locator": "#seg-main",
            },
        ]
    })
    return json.dumps(assistant_content)


def _write_provider_config(provider_dir: Path) -> None:
    """Write the chapter-marker provider configuration to Vidai Mock."""
    provider_file = provider_dir / "openai.yaml"
    provider_file.write_text(
        "\n".join((
            'name: "chapter_markers"',
            'matcher: "/v1/chat/completions"',
            "request_mapping:",
            "  model: \"{{ json.model | default(value='gpt-4o-mini') }}\"",
            'response_template: "chapter_markers/response.json.j2"',
        ))
        + "\n",
        encoding="utf-8",
    )


def _write_response_template(
    template_dir: Path,
    assistant_content_literal: str,
) -> None:
    """Write the chapter-marker response template to Vidai Mock."""
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
    "prompt_tokens": 60,
    "completion_tokens": 32,
    "total_tokens": 92
  }}
}}
""",
        encoding="utf-8",
    )


@given("a Vidai Mock chapter-marker server is running")
def vidaimock_server(
    chapter_markers_context: ChapterMarkersBDDContext,
    tmp_path: Path,
) -> None:
    """Start a local Vidai Mock instance with a chapter-marker template."""
    provider_dir = tmp_path / "providers"
    template_dir = tmp_path / "templates" / "chapter_markers"
    provider_dir.mkdir(parents=True)
    template_dir.mkdir(parents=True)

    _write_provider_config(provider_dir)
    _write_response_template(template_dir, _build_assistant_content_literal())
    start_vidaimock_process(
        chapter_markers_context,
        tmp_path,
        label="the chapter-marker behavioural test",
    )


@given("a TEI script body is prepared for chapter-marker extraction")
def prepare_chapter_marker_request(
    chapter_markers_context: ChapterMarkersBDDContext,
) -> None:
    """Build a TEI script body and segment metadata for chapter extraction."""
    chapter_markers_context.script_tei_xml = (
        '<TEI xmlns="http://www.tei-c.org/ns/1.0">'
        "<teiHeader><fileDesc><title>Episode 42</title></fileDesc></teiHeader>"
        "<text><body>"
        '<p xml:id="seg-intro">Welcome to episode 42.</p>'
        '<p xml:id="seg-main">Let us dive deep into the analysis.</p>'
        "</body></text>"
        "</TEI>"
    )
    chapter_markers_context.segment_structure = {
        "segments": [
            {"id": "seg-intro", "title": "Introduction", "start": "PT0S"},
            {"id": "seg-main", "title": "Main discussion", "start": "PT5M30S"},
        ]
    }


@when("the chapter-marker generator processes the script")
def run_chapter_marker_generation(
    chapter_markers_context: ChapterMarkersBDDContext,
) -> None:
    """Call the chapter-marker generator with a live LLM adapter."""

    async def _generate_chapter_markers() -> None:
        async with OpenAICompatibleLLMAdapter(
            config=OpenAICompatibleLLMConfig(
                base_url=chapter_markers_context.base_url,
                api_key="test-key",
            ),
        ) as adapter:
            recording_port = _RecordingLLMPort(wrapped=adapter)
            config = ChapterMarkersGeneratorConfig(
                model="gpt-4o-mini",
                provider_operation=LLMProviderOperation.CHAT_COMPLETIONS,
                token_budget=LLMTokenBudget(
                    max_input_tokens=1000,
                    max_output_tokens=500,
                    max_total_tokens=1500,
                ),
            )
            generator = ChapterMarkersGenerator(llm=recording_port, config=config)
            result = await generator.generate(
                chapter_markers_context.script_tei_xml,
                segment_structure=chapter_markers_context.segment_structure,
            )
            chapter_markers_context.result = result
            async with recording_port.lock:
                chapter_markers_context.request_payload = recording_port.requests[0]

    _run_async_step(_generate_chapter_markers)


@then("the generator returns structured chapter markers")
def assert_chapter_marker_result_structure(
    chapter_markers_context: ChapterMarkersBDDContext,
) -> None:
    """Verify the result contains chapter markers with expected fields."""
    result = chapter_markers_context.result
    assert result is not None, "Expected a ChapterMarkersResult, got None."
    assert len(result.chapters) == 2, "Expected values to match"
    assert result.chapters[0].title == "Introduction", "Expected values to match"
    assert result.chapters[0].start == "PT0S", "Expected values to match"
    assert result.chapters[0].tei_locator == "#seg-intro", "Expected values to match"
    assert result.chapters[1].title == "Main discussion", "Expected values to match"
    assert result.chapters[1].start == "PT5M30S", "Expected values to match"
    assert result.usage.input_tokens == 60, "Expected values to match"
    assert result.usage.output_tokens == 32, "Expected values to match"
    assert result.usage.total_tokens == 92, "Expected values to match"
    assert result.model == "gpt-4o-mini", "Expected values to match"
    assert result.finish_reason == "stop", "Expected values to match"


@then("the chapter-marker prompt includes the TEI script and segment metadata")
def assert_prompt_contains_tei_script_and_segments(
    chapter_markers_context: ChapterMarkersBDDContext,
) -> None:
    """Verify the actual outbound request includes TEI and segment metadata."""
    request = chapter_markers_context.request_payload
    assert request is not None, "Expected the adapter request to be captured."
    assert "Welcome to episode 42" in request.prompt, (
        "Expected collection to contain the value"
    )
    assert "script_tei_xml" in request.prompt, (
        "Expected collection to contain the value"
    )
    assert "segment_structure" in request.prompt, (
        "Expected collection to contain the value"
    )
    assert "seg-intro" in request.prompt, "Expected collection to contain the value"
    assert "PT5M30S" in request.prompt, "Expected collection to contain the value"


@then("the generated chapter markers enrich the TEI idempotently")
def assert_chapter_markers_enrich_tei_idempotently(
    chapter_markers_context: ChapterMarkersBDDContext,
) -> None:
    """Verify generated chapters produce one repeatable TEI chapter block."""
    result = chapter_markers_context.result
    assert result is not None, "Expected generated chapter markers."
    enriched_once = enrich_tei_with_chapter_markers(
        chapter_markers_context.script_tei_xml,
        result,
    )
    enriched_twice = enrich_tei_with_chapter_markers(enriched_once, result)
    assert enriched_twice == enriched_once, "Expected values to match"
    assert enriched_once.count('type="chapters"') == 1, "Expected values to match"
    assert '<item n="PT0S" corresp="#seg-intro">' in enriched_once, (
        "Expected collection to contain the value"
    )
    assert '<item n="PT5M30S" corresp="#seg-main">' in enriched_once, (
        "Expected collection to contain the value"
    )
    chapter_markers_context.enriched_tei_xml = enriched_once
