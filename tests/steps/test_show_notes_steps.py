"""Behavioural tests for the show notes generator."""

from __future__ import annotations

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
    ShowNotesGenerator,
    ShowNotesGeneratorConfig,
    ShowNotesResult,
)
from episodic.llm import LLMProviderOperation, LLMTokenBudget
from episodic.llm.openai_adapter import (
    OpenAICompatibleLLMAdapter,
    OpenAICompatibleLLMConfig,
)

if typ.TYPE_CHECKING:
    import asyncio
    import collections.abc as cabc
    from pathlib import Path


@dc.dataclass(slots=True)
class ShowNotesBDDContext:
    """Shared state between show notes BDD steps."""

    process: subprocess.Popen[str] | None = None
    base_url: str = ""
    script_tei_xml: str = ""
    template_structure: dict[str, object] | None = None
    result: ShowNotesResult | None = None
    prompt_text: str = ""


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
        ctx.process.terminate()
        try:
            ctx.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            ctx.process.kill()
            ctx.process.wait(timeout=5)


@scenario(
    "../features/show_notes.feature",
    "Show notes generator extracts topics from a TEI script via a live Vidai Mock server",
)
def test_show_notes_behaviour() -> None:
    """Run the show notes behaviour scenario."""


def _find_free_port() -> int:
    """Bind to an ephemeral port and return its number before releasing it."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _build_assistant_content_literal() -> str:
    """Build the double-encoded assistant content JSON literal.

    The OpenAI chat-completion schema requires ``message.content`` to be a JSON
    string, not a raw object. The inner ``json.dumps`` produces the show-notes
    result object; the outer ``json.dumps`` wraps it in a JSON string literal so
    that the Jinja template emits a valid ``"content": "<escaped-json>"`` field.
    """
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
    provider_file = provider_dir / "show_notes.yaml"
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


_VIDAIMOCK_STARTUP_TIMEOUT = 5.0
_VIDAIMOCK_PROBE_INTERVAL = 0.2


def _handle_connect_failure(
    process: subprocess.Popen[str],
    deadline: float,
) -> None:
    """Raise if the deadline has passed; otherwise sleep before the next probe."""
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
    """Poll a TCP port until the server accepts connections or the deadline expires."""
    deadline = time.monotonic() + timeout
    while True:
        if process.poll() is not None:
            msg = "Vidai Mock failed to start for the show notes behavioural test."
            raise RuntimeError(msg)
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return
        except OSError:
            _handle_connect_failure(process, deadline)


def _start_vidaimock_process(
    show_notes_context: ShowNotesBDDContext,
    config_dir: Path,
    port: int,
) -> None:
    """Start the Vidai Mock server and verify it started successfully."""
    vidaimock_path = shutil.which("vidaimock")
    if vidaimock_path is None:
        msg = "vidaimock executable not found in PATH"
        raise RuntimeError(msg)

    show_notes_context.base_url = f"http://127.0.0.1:{port}/v1"
    show_notes_context.process = subprocess.Popen(  # noqa: S603
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

    _await_port_ready(show_notes_context.process, "127.0.0.1", port)


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

    port = _find_free_port()

    _start_vidaimock_process(show_notes_context, tmp_path, port)


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
        adapter = OpenAICompatibleLLMAdapter(
            config=OpenAICompatibleLLMConfig(
                base_url=show_notes_context.base_url,
                api_key="test-key",
            ),
        )

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

        result = await generator.generate(
            show_notes_context.script_tei_xml,
            template_structure=show_notes_context.template_structure,
        )

        show_notes_context.result = result

        # Capture the prompt for inspection
        show_notes_context.prompt_text = generator.build_prompt(
            show_notes_context.script_tei_xml,
            template_structure=show_notes_context.template_structure,
        )

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
    assert first_entry.topic == "Introduction"
    assert "Opening remarks" in first_entry.summary
    assert first_entry.timestamp == "PT0M30S"

    second_entry = result.entries[1]
    assert second_entry.topic == "Main Discussion"
    assert "In-depth analysis" in second_entry.summary
    assert second_entry.timestamp == "PT5M15S"

    # Verify normalized usage metadata
    assert result.usage.input_tokens == 50
    assert result.usage.output_tokens == 30
    assert result.usage.total_tokens == 80
    assert result.model == "gpt-4o-mini"
    assert result.finish_reason == "stop"


@then("the show-notes prompt includes the TEI script body")
def assert_prompt_contains_tei_script(show_notes_context: ShowNotesBDDContext) -> None:
    """Verify the prompt includes the TEI script XML."""
    prompt = show_notes_context.prompt_text
    assert "Welcome to episode 42" in prompt, (
        "Expected prompt to contain script text from the TEI body."
    )
    assert "script_tei_xml" in prompt, (
        "Expected prompt to include the script_tei_xml key."
    )
