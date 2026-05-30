"""Behavioural tests for the OpenAI-compatible LLM adapter."""

from __future__ import annotations

import dataclasses as dc
import json
import threading
import typing as typ
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from pytest_bdd import given, scenario, then, when

from episodic.canonical.prompts import (
    RenderedPrompt,
    render_series_brief_prompt,
    render_series_guardrail_prompt,
)
from episodic.llm import (
    LLMRequest,
    LLMTokenBudget,
    OpenAICompatibleLLMAdapter,
    OpenAICompatibleLLMConfig,
)

if typ.TYPE_CHECKING:
    import asyncio
    import collections.abc as cabc


@dc.dataclass(slots=True)
class MockServerState:
    """Shared mutable state for the local mock LLM server."""

    requests: list[dict[str, object]] = dc.field(default_factory=list)
    call_count: int = 0


@dc.dataclass(slots=True)
class LLMAdapterContext:
    """Shared state between LLM adapter BDD steps."""

    base_url: str = ""
    server: ThreadingHTTPServer | None = None
    server_thread: threading.Thread | None = None
    server_state: MockServerState = dc.field(default_factory=MockServerState)
    rendered_prompt: RenderedPrompt | None = None
    guardrail_prompt: RenderedPrompt | None = None
    generated_text: str = ""


class _MockLLMHandler(BaseHTTPRequestHandler):
    """Serve a minimal OpenAI-compatible chat-completions endpoint."""

    server: _MockLLMServer

    def do_POST(self) -> None:
        """Handle one OpenAI-compatible chat-completions request."""
        content_length = int(self.headers["content-length"])
        raw_body = self.rfile.read(content_length)
        payload = json.loads(raw_body.decode("utf-8"))

        self.server.state.call_count += 1
        self.server.state.requests.append(typ.cast("dict[str, object]", payload))

        if self.server.fail_first and self.server.state.call_count == 1:
            self.send_response(HTTPStatus.TOO_MANY_REQUESTS)
            self.send_header("content-type", "application/json")
            self.end_headers()
            self.wfile.write(
                json.dumps({"error": {"message": "retry later"}}).encode("utf-8")
            )
            return

        self.send_response(HTTPStatus.OK)
        self.send_header("content-type", "application/json")
        self.end_headers()
        self.wfile.write(
            json.dumps({
                "id": "chatcmpl-bdd",
                "model": "gpt-4o-mini",
                "choices": [
                    {
                        "message": {"content": "BDD generated episode draft."},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 40,
                    "completion_tokens": 12,
                    "total_tokens": 52,
                },
            }).encode("utf-8")
        )

    # Required stdlib override signature for keyword-compatible dispatch.
    def log_message(self, message_format: str, *args: object) -> None:  # ty: ignore[invalid-method-override]
        """Suppress stdlib HTTP server request logging in tests."""
        del message_format, args


class _MockLLMServer(ThreadingHTTPServer):
    """HTTP server carrying mutable test state."""

    # pylint: disable-next=too-many-arguments
    def __init__(
        self,
        server_address: tuple[str, int],
        handler_class: type[BaseHTTPRequestHandler],
        *,
        state: MockServerState,
        fail_first: bool = False,
    ) -> None:
        super().__init__(server_address, handler_class)
        self.state = state
        self.fail_first = fail_first


@dc.dataclass(frozen=True, slots=True, kw_only=True)
class _GenerateOptions:
    """Per-call generation parameters for the BDD adapter helper."""

    max_attempts: int
    token_budget: LLMTokenBudget
    retry_delay_seconds: float = 0.0
    chars_per_token: float = 4.0


def _start_mock_server(context: LLMAdapterContext, *, fail_first: bool) -> None:
    """Start a mock LLM server and populate *context* with connection details."""
    server = _MockLLMServer(
        ("127.0.0.1", 0),
        _MockLLMHandler,
        state=context.server_state,
        fail_first=fail_first,
    )
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    context.server = server
    context.server_thread = server_thread
    context.base_url = f"http://127.0.0.1:{server.server_address[1]}/v1"


def _run_generate(
    runner: asyncio.Runner,
    context: LLMAdapterContext,
    options: _GenerateOptions,
) -> None:
    """Run ``adapter.generate()`` via *runner* and store the result in *context*."""

    async def _generate() -> None:
        async with OpenAICompatibleLLMAdapter(
            config=OpenAICompatibleLLMConfig(
                base_url=context.base_url,
                api_key="test-key",
                max_attempts=options.max_attempts,
                retry_delay_seconds=options.retry_delay_seconds,
                chars_per_token=options.chars_per_token,
            ),
        ) as adapter:
            response = await adapter.generate(
                LLMRequest(
                    model="gpt-4o-mini",
                    prompt=typ.cast("RenderedPrompt", context.rendered_prompt).text,
                    system_prompt=typ.cast(
                        "RenderedPrompt", context.guardrail_prompt
                    ).text,
                    token_budget=options.token_budget,
                ),
            )
        context.generated_text = response.text

    _run_async_step(runner, _generate)


def _run_async_step(
    runner: asyncio.Runner,
    step_fn: cabc.Callable[[], cabc.Awaitable[None]],
) -> None:
    """Execute an async BDD step via the provided runner."""
    runner.run(step_fn())


@pytest.fixture
def context() -> cabc.Iterator[LLMAdapterContext]:
    """Share state between LLM adapter BDD steps and clean up the server."""
    ctx = LLMAdapterContext()
    yield ctx
    if ctx.server is not None:
        ctx.server.shutdown()
        ctx.server.server_close()
    if ctx.server_thread is not None:
        ctx.server_thread.join(timeout=1)


@scenario(
    "../features/llm_adapter.feature",
    "Adapter retries transient failures and sends persisted guardrails",
)
def test_llm_adapter_behaviour() -> None:
    """Run the LLM adapter behaviour scenario."""


@scenario(
    "../features/llm_adapter.feature",
    "Adapter applies a configured chars-per-token ratio for token estimation",
)
def test_llm_adapter_custom_chars_per_token() -> None:
    """Run the custom chars-per-token BDD scenario."""


@given("an OpenAI-compatible mock LLM server is running")
def mock_llm_server(context: LLMAdapterContext) -> None:
    """Start a localhost HTTP server with one transient failure."""
    _start_mock_server(context, fail_first=True)


@given("a rendered series prompt and persisted guardrail prompt are available")
def rendered_prompts_available(context: LLMAdapterContext) -> None:
    """Render prompt and guardrail text from one structured brief payload."""
    brief: dict[str, object] = {
        "series_profile": {
            "id": "profile-1",
            "slug": "signal-weekly",
            "title": "Signal Weekly",
            "description": "A measured explainer show.",
            "configuration": {"tone": "measured"},
            "guardrails": {
                "instruction": "Avoid hype and keep claims attributable.",
                "banned_phrases": ["game changer"],
            },
        },
        "episode_templates": [
            {
                "id": "template-1",
                "series_profile_id": "profile-1",
                "slug": "weekly-briefing",
                "title": "Weekly Briefing",
                "description": "A weekly recap format.",
                "structure": {"segments": ["intro", "news", "outro"]},
                "guardrails": {
                    "instruction": "End with a recap.",
                    "required_sections": ["intro", "news", "outro"],
                },
            }
        ],
        "reference_documents": [],
    }
    context.rendered_prompt = render_series_brief_prompt(brief)
    context.guardrail_prompt = render_series_guardrail_prompt(brief)


@when("the OpenAI-compatible adapter generates episode content")
def adapter_generates(
    _function_scoped_runner: asyncio.Runner,
    context: LLMAdapterContext,
) -> None:
    """Generate text through the adapter over real HTTP."""
    _run_generate(
        _function_scoped_runner,
        context,
        _GenerateOptions(
            max_attempts=2,
            token_budget=LLMTokenBudget(
                max_input_tokens=500,
                max_output_tokens=200,
                max_total_tokens=700,
            ),
        ),
    )


@then("the adapter retries once and returns the generated text")
def assert_generated_text(context: LLMAdapterContext) -> None:
    """Assert retry behaviour and final generated content."""
    assert context.server_state.call_count == 2, (
        "adapter should retry once before succeeding"
    )
    assert context.generated_text == "BDD generated episode draft.", (
        "adapter should return the generated draft text from the mock server"
    )


@then("the outbound request includes the persisted guardrail prompt")
def assert_guardrail_prompt(context: LLMAdapterContext) -> None:
    """Assert outbound system guardrails, user content, and token budgeting."""
    latest_request = context.server_state.requests[-1]
    messages = typ.cast("list[dict[str, str]]", latest_request["messages"])

    assert messages[0]["role"] == "system", (
        "first outbound message should be the system guardrail prompt"
    )
    assert "Avoid hype and keep claims attributable." in messages[0]["content"], (
        "system guardrail prompt should include persisted profile guardrails"
    )
    assert "End with a recap." in messages[0]["content"], (
        "system guardrail prompt should include persisted template guardrails"
    )
    assert len(messages) >= 2, (
        "outbound request should include both system and user messages"
    )
    assert messages[1]["role"] == "user", (
        "second outbound message should be the rendered user prompt"
    )
    assert (
        messages[1]["content"]
        == typ.cast("RenderedPrompt", context.rendered_prompt).text
    ), "user message content should equal the rendered prompt text"
    assert "Series slug: signal-weekly" in messages[1]["content"], (
        "rendered user prompt should include the expected series slug"
    )
    assert latest_request["max_tokens"] == 200, (
        "request should cap output tokens at the configured budget"
    )


@given("an OpenAI-compatible mock LLM server is running without transient failures")
def mock_llm_server_always_succeeds(context: LLMAdapterContext) -> None:
    """Start a localhost HTTP server that always responds successfully."""
    _start_mock_server(context, fail_first=False)


@when(
    "the OpenAI-compatible adapter generates content "
    "with a custom chars-per-token ratio"
)
def adapter_generates_custom_ratio(
    _function_scoped_runner: asyncio.Runner,
    context: LLMAdapterContext,
) -> None:
    """Generate text with chars_per_token=2.0 over real HTTP."""
    _run_generate(
        _function_scoped_runner,
        context,
        _GenerateOptions(
            max_attempts=1,
            chars_per_token=2.0,
            token_budget=LLMTokenBudget(
                max_input_tokens=2000,
                max_output_tokens=200,
                max_total_tokens=2200,
            ),
        ),
    )


@then("the adapter returns the generated text on the first attempt")
def assert_generated_first_attempt(context: LLMAdapterContext) -> None:
    """Assert no retry occurred and the generated text is correct."""
    assert context.server_state.call_count == 1, (
        "adapter should succeed on the first attempt with no transient failure"
    )
    assert context.generated_text == "BDD generated episode draft.", (
        "adapter should return generated text when chars_per_token=2.0 is configured"
    )
