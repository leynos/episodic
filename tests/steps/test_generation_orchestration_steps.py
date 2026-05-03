"""Behavioural tests for structured generation orchestration."""

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

from episodic.llm.openai_adapter import (
    OpenAICompatibleLLMAdapter,
    OpenAICompatibleLLMConfig,
)
from episodic.orchestration import (
    ActionKind,
    GenerationOrchestrationConfig,
    GenerationOrchestrationRequest,
    ShowNotesToolExecutor,
    StructuredGenerationPlanner,
    StructuredPlanningOrchestrator,
)

if typ.TYPE_CHECKING:
    import asyncio
    import collections.abc as cabc
    from pathlib import Path

    from episodic.llm.ports import LLMPort, LLMRequest, LLMResponse
    from episodic.orchestration import GenerationOrchestrationResult


@dc.dataclass(slots=True)
class OrchestrationBDDContext:
    """Shared state between orchestration BDD steps."""

    process: subprocess.Popen[str] | None = None
    base_url: str = ""
    request: GenerationOrchestrationRequest | None = None
    result: GenerationOrchestrationResult | None = None
    requests: list[LLMRequest] = dc.field(default_factory=list)


@dc.dataclass(slots=True)
class _RecordingLLMPort:
    """Capture the actual `LLMRequest` values before delegating."""

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
def orchestration_context() -> cabc.Iterator[OrchestrationBDDContext]:
    """Share state between BDD steps and stop Vidai Mock afterward."""
    ctx = OrchestrationBDDContext()
    yield ctx
    if ctx.process is not None:
        ctx.process.terminate()
        try:
            ctx.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            ctx.process.kill()
            ctx.process.wait(timeout=5)


@scenario(
    "../features/generation_orchestration.feature",
    "Orchestrator plans a structured generation run and executes show notes",
)
def test_generation_orchestration_behaviour() -> None:
    """Run the structured generation orchestration scenario."""


def _find_free_port() -> int:
    """Bind to an ephemeral port and return its number before releasing it."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _planner_content_literal() -> str:
    planner_content = json.dumps({
        "plan_version": "1.0",
        "steps": [
            {
                "action_id": "action-1",
                "action_kind": "generate_show_notes",
                "rationale": "Generate show notes for publication channels.",
                "model_tier": "execution",
                "required_inputs": ["script_tei_xml", "template_structure"],
            }
        ],
    })
    return json.dumps(planner_content)


def _show_notes_content_literal() -> str:
    show_notes_content = json.dumps({
        "entries": [
            {
                "topic": "Introduction",
                "summary": "Opening remarks and episode overview.",
                "timestamp": "PT0M30S",
            }
        ]
    })
    return json.dumps(show_notes_content)


def _write_provider_config(provider_dir: Path) -> None:
    provider_file = provider_dir / "orchestration.yaml"
    provider_file.write_text(
        "\n".join((
            'name: "orchestration"',
            'matcher: "/v1/chat/completions"',
            "request_mapping:",
            "  model: \"{{ json.model | default(value='gpt-4o-mini') }}\"",
            'response_template: "orchestration/response.json.j2"',
        ))
        + "\n",
        encoding="utf-8",
    )


def _write_response_template(template_dir: Path) -> None:
    template_file = template_dir / "response.json.j2"
    template_file.write_text(
        """{
  "id": "chatcmpl-{{ uuid() }}",
  "created": {{ timestamp() }},
  "object": "chat.completion",
  "model": "{{ model }}",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content":
          {% if model == "gpt-4.1" %}
          {{ planner_content }}
          {% elif model == "gpt-4o-mini" %}
          {{ show_notes_content }}
          {% else %}
          "{}"
          {% endif %}
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": {% if model == "gpt-4.1" %}41{% else %}19{% endif %},
    "completion_tokens": {% if model == "gpt-4.1" %}13{% else %}8{% endif %},
    "total_tokens": {% if model == "gpt-4.1" %}54{% else %}27{% endif %}
  }
}
""".replace("{{ planner_content }}", _planner_content_literal()).replace(
            "{{ show_notes_content }}",
            _show_notes_content_literal(),
        ),
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
            msg = "Vidai Mock failed to start for the orchestration behavioural test."
            raise RuntimeError(msg)
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return
        except OSError:
            _handle_connect_failure(process, deadline)


def _start_vidaimock_process(
    orchestration_context: OrchestrationBDDContext,
    config_dir: Path,
    port: int,
) -> None:
    vidaimock_path = shutil.which("vidaimock")
    if vidaimock_path is None:
        pytest.skip("vidaimock executable not found in PATH")

    orchestration_context.base_url = f"http://127.0.0.1:{port}/v1"
    orchestration_context.process = subprocess.Popen(  # noqa: S603
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

    _await_port_ready(orchestration_context.process, "127.0.0.1", port)


@given("a Vidai Mock orchestration server is running")
def vidaimock_server(
    orchestration_context: OrchestrationBDDContext,
    tmp_path: Path,
) -> None:
    """Start a local Vidai Mock instance for the orchestration flow."""
    provider_dir = tmp_path / "providers"
    template_dir = tmp_path / "templates" / "orchestration"
    provider_dir.mkdir(parents=True)
    template_dir.mkdir(parents=True)

    _write_provider_config(provider_dir)
    _write_response_template(template_dir)
    _start_vidaimock_process(orchestration_context, tmp_path, port=_find_free_port())


@given("a generation orchestration request is prepared")
def prepare_request(orchestration_context: OrchestrationBDDContext) -> None:
    """Create the generation request used by the orchestration scenario."""
    orchestration_context.request = GenerationOrchestrationRequest(
        correlation_id="bdd-correlation",
        script_tei_xml=(
            "<TEI><text><body><p>Welcome to episode 42.</p>"
            "<p>We discuss the main topic.</p></body></text></TEI>"
        ),
        template_structure={"sections": ["intro", "discussion"]},
    )


@when("the orchestration service plans and executes the request")
def run_orchestration(
    _function_scoped_runner: asyncio.Runner,
    orchestration_context: OrchestrationBDDContext,
) -> None:
    """Call the orchestration service with a live LLM adapter."""

    async def _orchestrate() -> None:
        request = orchestration_context.request
        if request is None:
            msg = "generation request was not prepared"
            raise AssertionError(msg)

        async with OpenAICompatibleLLMAdapter(
            config=OpenAICompatibleLLMConfig(
                base_url=orchestration_context.base_url,
                api_key="test-key",
            ),
        ) as adapter:
            recording_port = _RecordingLLMPort(wrapped=adapter)
            config = GenerationOrchestrationConfig(
                planning_model="gpt-4.1",
                execution_model="gpt-4o-mini",
            )
            orchestrator = StructuredPlanningOrchestrator(
                planner=StructuredGenerationPlanner(
                    llm=recording_port,
                    config=config,
                ),
                tool_executor=ShowNotesToolExecutor(
                    llm=recording_port,
                    config=config,
                ),
            )

            orchestration_context.result = await orchestrator.orchestrate(request)
            orchestration_context.requests = recording_port.requests

    _run_async_step(_function_scoped_runner, _orchestrate)


@then("the orchestration result includes a structured plan and show-notes output")
def assert_result(orchestration_context: OrchestrationBDDContext) -> None:
    """Verify the orchestration result exposes the plan and action output."""
    result = orchestration_context.result
    assert result is not None, "Expected orchestration result, got None."
    assert result.plan.plan_version == "1.0"
    assert result.plan.steps[0].action_kind is ActionKind.GENERATE_SHOW_NOTES
    assert result.action_results[0].show_notes_result is not None
    assert result.action_results[0].show_notes_result.entries[0].topic == "Introduction"
    assert result.total_usage.total_tokens == 81


@then("the orchestration requests use planning and execution models in order")
def assert_requests(orchestration_context: OrchestrationBDDContext) -> None:
    """Verify the planner call happens before the execution-stage tool call."""
    requests = orchestration_context.requests
    assert [request.model for request in requests] == ["gpt-4.1", "gpt-4o-mini"]
    assert "enabled_action_kinds" in requests[0].prompt
    assert "script_tei_xml" in requests[1].prompt
