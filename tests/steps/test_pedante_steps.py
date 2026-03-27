"""Behavioural tests for the Pedante evaluator."""

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

from episodic.llm import LLMProviderOperation, LLMTokenBudget
from episodic.llm.openai_adapter import (
    OpenAICompatibleLLMAdapter,
    OpenAICompatibleLLMConfig,
)
from episodic.qa.pedante import (
    PedanteEvaluationRequest,
    PedanteEvaluator,
    PedanteEvaluatorConfig,
    PedanteSourcePacket,
)

if typ.TYPE_CHECKING:
    import asyncio
    import collections.abc as cabc
    from pathlib import Path

    from episodic.qa.pedante import PedanteEvaluationResult


@dc.dataclass(slots=True)
class PedanteBDDContext:
    """Shared state between Pedante BDD steps."""

    process: subprocess.Popen[str] | None = None
    base_url: str = ""
    request: PedanteEvaluationRequest | None = None
    result: PedanteEvaluationResult | None = None
    prompt_text: str = ""


def _run_async_step(
    runner: asyncio.Runner,
    step_fn: cabc.Callable[[], cabc.Awaitable[None]],
) -> None:
    """Execute an async BDD step via the provided runner."""
    runner.run(step_fn())


@pytest.fixture
def pedante_context() -> cabc.Iterator[PedanteBDDContext]:
    """Share state between Pedante BDD steps and stop Vidai Mock afterward."""
    ctx = PedanteBDDContext()
    yield ctx
    if ctx.process is not None:
        ctx.process.terminate()
        try:
            ctx.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            ctx.process.kill()
            ctx.process.wait(timeout=5)


@scenario(
    "../features/pedante.feature",
    "Pedante returns structured findings from a live Vidai Mock server",
)
def test_pedante_behaviour() -> None:
    """Run the Pedante behaviour scenario."""


def _build_assistant_content_literal() -> str:
    """Build the double-encoded assistant content JSON literal.

    The OpenAI chat-completion schema requires ``message.content`` to be a JSON
    string, not a raw object.  The inner ``json.dumps`` produces the Pedante
    result object; the outer ``json.dumps`` wraps it in a JSON string literal so
    that the Jinja template emits a valid ``"content": "<escaped-json>"`` field.
    """
    assistant_content = json.dumps({
        "summary": "One likely inaccuracy requires revision.",
        "findings": [
            {
                "claim_id": "claim-1",
                "claim_text": "The launch happened in January 2025.",
                "claim_kind": "inference",
                "support_level": "inference_not_supported",
                "severity": "critical",
                "summary": ("The cited source does not support a January 2025 launch."),
                "remediation": ("Remove the date or cite a supporting source."),
                "cited_source_ids": ["src-1"],
            }
        ],
    })
    return json.dumps(assistant_content)


def _write_provider_config(provider_dir: Path) -> None:
    """Write the Pedante provider configuration to Vidai Mock."""
    provider_file = provider_dir / "pedante.yaml"
    provider_file.write_text(
        "\n".join((
            'name: "pedante"',
            'matcher: "/v1/chat/completions"',
            "request_mapping:",
            "  model: \"{{ json.model | default(value='gpt-4o-mini') }}\"",
            'response_template: "pedante/response.json.j2"',
        ))
        + "\n",
        encoding="utf-8",
    )


def _write_response_template(
    template_dir: Path,
    assistant_content_literal: str,
) -> None:
    """Write the Pedante response template to Vidai Mock."""
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
    "prompt_tokens": 32,
    "completion_tokens": 18,
    "total_tokens": 50
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
            msg = "Vidai Mock failed to start for the Pedante behavioural test."
            raise RuntimeError(msg)
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return
        except OSError:
            _handle_connect_failure(process, deadline)


def _start_vidaimock_process(
    pedante_context: PedanteBDDContext,
    config_dir: Path,
    port: int,
) -> None:
    """Start the Vidai Mock server and verify it started successfully."""
    vidaimock_path = shutil.which("vidaimock")
    if vidaimock_path is None:
        msg = "vidaimock executable not found in PATH"
        raise RuntimeError(msg)

    pedante_context.base_url = f"http://127.0.0.1:{port}/v1"
    pedante_context.process = subprocess.Popen(  # noqa: S603
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

    _await_port_ready(pedante_context.process, "127.0.0.1", port)


# ── BDD step ──


@given("a Vidai Mock Pedante server is running")
def vidaimock_server(
    pedante_context: PedanteBDDContext,
    tmp_path: Path,
) -> None:
    """Start a local Vidai Mock instance with a Pedante-specific template."""
    provider_dir = tmp_path / "providers"
    template_dir = tmp_path / "templates" / "pedante"
    provider_dir.mkdir(parents=True)
    template_dir.mkdir(parents=True)

    assistant_content_literal = _build_assistant_content_literal()
    _write_provider_config(provider_dir)
    _write_response_template(template_dir, assistant_content_literal)
    _start_vidaimock_process(pedante_context, tmp_path, port=18110)


@given("a TEI-backed Pedante evaluation request is prepared")
def prepare_request(pedante_context: PedanteBDDContext) -> None:
    """Create a canonical Pedante request with TEI XML and one source packet."""
    pedante_context.request = PedanteEvaluationRequest(
        script_tei_xml=(
            "<TEI><text><body><p xml:id='claim-1'>"
            "The launch happened in January 2025.[Source 1]"
            "</p></body></text></TEI>"
        ),
        sources=(
            PedanteSourcePacket(
                source_id="src-1",
                citation_label="Source 1",
                tei_locator="//body/div[@xml:id='source-1']/p[1]",
                title="Primary source",
                excerpt=(
                    "The source describes planning work in 2024 but no launch date."
                ),
            ),
        ),
    )


@when("Pedante evaluates the script for factual support")
def evaluate_script(
    _function_scoped_runner: asyncio.Runner,
    pedante_context: PedanteBDDContext,
) -> None:
    """Run Pedante over the live Vidai Mock-backed OpenAI adapter."""

    async def _evaluate() -> None:
        async with OpenAICompatibleLLMAdapter(
            config=OpenAICompatibleLLMConfig(
                base_url=pedante_context.base_url,
                api_key="test-key",
            ),
        ) as adapter:
            evaluator = PedanteEvaluator(
                llm=adapter,
                config=PedanteEvaluatorConfig(
                    model="gpt-4o-mini",
                    provider_operation=LLMProviderOperation.CHAT_COMPLETIONS,
                    token_budget=LLMTokenBudget(
                        max_input_tokens=500,
                        max_output_tokens=200,
                        max_total_tokens=700,
                    ),
                ),
            )
            request = typ.cast("PedanteEvaluationRequest", pedante_context.request)
            pedante_context.prompt_text = evaluator.build_prompt(request)
            pedante_context.result = await evaluator.evaluate(request)

    _run_async_step(_function_scoped_runner, _evaluate)


@then("Pedante returns structured findings and normalized usage")
def assert_result(pedante_context: PedanteBDDContext) -> None:
    """Assert findings, usage, and metadata survive the live adapter path."""
    result = typ.cast("PedanteEvaluationResult", pedante_context.result)
    assert result.summary == "One likely inaccuracy requires revision."
    assert result.usage.input_tokens == 32
    assert result.usage.output_tokens == 18
    assert result.usage.total_tokens == 50
    assert result.requires_revision is True
    assert len(result.findings) == 1
    assert result.findings[0].claim_id == "claim-1"
    assert result.findings[0].cited_source_ids == ("src-1",)

    assert result.model == "gpt-4o-mini"
    assert result.provider_response_id.startswith("chatcmpl-")


@then("the Pedante prompt includes TEI XML and cited source packets")
def assert_prompt(pedante_context: PedanteBDDContext) -> None:
    """Assert prompt construction stays on the TEI-backed request spine."""
    assert "<TEI>" in pedante_context.prompt_text
    assert "Source 1" in pedante_context.prompt_text
    assert "tei_locator" in pedante_context.prompt_text
