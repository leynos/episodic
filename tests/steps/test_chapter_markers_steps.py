"""Behavioural tests for live chapter-marker inference.

This module verifies the adapter-facing path that unit tests intentionally
avoid. It starts Vidai Mock with an OpenAI-compatible chat-completion template,
uses the real `OpenAICompatibleLLMAdapter`, records the outbound `LLMRequest`,
and drives `ChapterMarkersGenerator` through pytest-bdd steps.

The scenario proves the component relationships across the generation service,
LLM port, OpenAI-compatible adapter, Vidai Mock test server, and TEI enrichment
helper. The local server is process-scoped to the fixture and cleaned up
through the same termination helper used when startup retries fail.
"""

from __future__ import annotations

import asyncio
import dataclasses as dc
import json
import shutil
import socket
import subprocess  # noqa: S404 - required to start a local Vidai Mock test server
import time
import typing as typ

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

if typ.TYPE_CHECKING:
    import collections.abc as cabc
    from pathlib import Path

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
        _terminate_process_gracefully(ctx.process)


@scenario(
    "../features/chapter_markers.feature",
    "Chapter marker generator creates chapters from a TEI script via a live "
    "Vidai Mock server",
)
def test_chapter_markers_behaviour() -> None:
    """Run the chapter-marker behaviour scenario."""


def _find_free_port() -> int:
    """Bind to an ephemeral port and return its number before releasing it."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


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
    provider_file = provider_dir / "chapter_markers.yaml"
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


_VIDAIMOCK_STARTUP_TIMEOUT = 5.0
_VIDAIMOCK_PROBE_INTERVAL = 0.2
_VIDAIMOCK_PORT_START_ATTEMPTS = 5


def _handle_connect_failure(
    process: subprocess.Popen[str],
    deadline: float,
) -> None:
    """Raise if the deadline has passed; otherwise sleep before probing again."""
    if time.monotonic() < deadline:
        time.sleep(_VIDAIMOCK_PROBE_INTERVAL)
        return
    if process.poll() is None:
        process.terminate()
    msg = "Vidai Mock did not become ready within the timeout."
    raise RuntimeError(msg) from None


def _await_port_ready(
    process: subprocess.Popen[str],
    host: str,
    port: int,
    timeout: float = _VIDAIMOCK_STARTUP_TIMEOUT,
) -> None:
    """Poll a TCP port until the server accepts connections or times out."""
    deadline = time.monotonic() + timeout
    while True:
        if process.poll() is not None:
            msg = "Vidai Mock failed to start for the chapter-marker test."
            raise RuntimeError(msg)
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return
        except OSError:
            _handle_connect_failure(process, deadline)


def _terminate_process_gracefully(process: subprocess.Popen[str]) -> None:
    """Terminate *process*, escalating to SIGKILL if it does not exit promptly."""
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def _start_vidaimock_process(
    chapter_markers_context: ChapterMarkersBDDContext,
    config_dir: Path,
) -> None:
    """Start Vidai Mock, retrying ports to reduce bind races."""
    vidaimock_path = shutil.which("vidaimock")
    if vidaimock_path is None:
        pytest.skip("vidaimock executable not found in PATH")
    last_error: RuntimeError | None = None
    for _ in range(_VIDAIMOCK_PORT_START_ATTEMPTS):
        port = _find_free_port()
        process = subprocess.Popen(  # noqa: S603 - fixed trusted local binary.  # pylint: disable=consider-using-with
            [
                vidaimock_path,
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--config-dir",
                str(config_dir),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        try:
            _await_port_ready(process, "127.0.0.1", port)
        except RuntimeError as exc:
            _terminate_process_gracefully(process)
            last_error = exc
            continue

        chapter_markers_context.base_url = f"http://127.0.0.1:{port}/v1"
        chapter_markers_context.process = process
        return

    msg = "Vidai Mock failed to start for the chapter-marker test."
    raise RuntimeError(msg) from last_error


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
    _start_vidaimock_process(chapter_markers_context, tmp_path)


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
    assert len(result.chapters) == 2
    assert result.chapters[0].title == "Introduction"
    assert result.chapters[0].start == "PT0S"
    assert result.chapters[0].tei_locator == "#seg-intro"
    assert result.chapters[1].title == "Main discussion"
    assert result.chapters[1].start == "PT5M30S"
    assert result.usage.input_tokens == 60
    assert result.usage.output_tokens == 32
    assert result.usage.total_tokens == 92
    assert result.model == "gpt-4o-mini"
    assert result.finish_reason == "stop"


@then("the chapter-marker prompt includes the TEI script and segment metadata")
def assert_prompt_contains_tei_script_and_segments(
    chapter_markers_context: ChapterMarkersBDDContext,
) -> None:
    """Verify the actual outbound request includes TEI and segment metadata."""
    request = chapter_markers_context.request_payload
    assert request is not None, "Expected the adapter request to be captured."
    assert "Welcome to episode 42" in request.prompt
    assert "script_tei_xml" in request.prompt
    assert "segment_structure" in request.prompt
    assert "seg-intro" in request.prompt
    assert "PT5M30S" in request.prompt


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

    assert enriched_twice == enriched_once
    assert enriched_once.count('type="chapters"') == 1
    assert '<item n="PT0S" corresp="#seg-intro">' in enriched_once
    assert '<item n="PT5M30S" corresp="#seg-main">' in enriched_once
    chapter_markers_context.enriched_tei_xml = enriched_once
