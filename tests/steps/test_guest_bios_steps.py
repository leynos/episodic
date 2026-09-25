"""Behavioural tests for guest biography generation.

This module binds `tests/features/guest_bios.feature` steps to a live Vidai
Mock-backed `LLMPort` flow. Each scenario starts a local Vidai Mock process
from a temporary provider/template directory, waits for the TCP port to become
ready, and tears the process down through the `guest_bios_context` fixture.

The `_RecordingLLMPort` wrapper records every `LLMRequest` before forwarding it
to the OpenAI-compatible adapter. Step assertions use that captured request to
prove `GuestBiosGenerator.generate` sent pinned guest profile content, while
also recording generated `GuestBiosResult` and enriched TEI artefacts for the
Then steps.
"""

from __future__ import annotations

import asyncio  # noqa: TC003 - pytest-bdd inspects step annotations at runtime.
import dataclasses as dc
import json
import typing as typ
from pathlib import (
    Path,  # noqa: TC003 - pytest-bdd inspects step annotations at runtime.
)

import pytest
import yaml
from pytest_bdd import given, scenario, then, when

from episodic.generation import (
    GuestBiosGenerator,
    GuestBiosGeneratorConfig,
    GuestBioSource,
    GuestBiosResult,
    enrich_tei_with_guest_bios,
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
class GuestBiosBDDContext:
    """Shared state between guest-bios BDD steps."""

    process: subprocess.Popen[str] | None = None
    base_url: str = ""
    script_tei_xml: str = ""
    sources: tuple[GuestBioSource, ...] = ()
    result: GuestBiosResult | None = None
    enriched_tei_xml: str = ""
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
def guest_bios_context() -> cabc.Iterator[GuestBiosBDDContext]:
    """Share state between guest-bios BDD steps and stop Vidai Mock afterward."""
    ctx = GuestBiosBDDContext()
    yield ctx
    if ctx.process is not None:
        terminate_process_gracefully(ctx.process, ctx.stderr_file)


@scenario(
    "../features/guest_bios.feature",
    "Guest-bios generator summarizes pinned guest profiles via a live Vidai "
    "Mock server",
)
def test_guest_bios_behaviour() -> None:
    """Run the guest-bios behaviour scenario."""


def _build_assistant_content_literal() -> str:
    """Build the double-encoded assistant content JSON literal."""
    assistant_content = json.dumps({
        "guests": [
            {
                "display_name": "Ada Lovelace",
                "bio": "Ada Lovelace wrote about analytical engines.",
                "reference_document_revision_id": "rev-ada",
                "role": "Mathematician",
            }
        ]
    })
    return json.dumps(assistant_content)


def _write_provider_config(provider_dir: Path) -> None:
    """Write the guest-bios provider configuration to Vidai Mock."""
    provider_file = provider_dir / "openai.yaml"
    provider_config = {
        "name": "guest_bios",
        "matcher": "/v1/chat/completions",
        "request_mapping": {
            "model": "{{ json.model | default(value='gpt-4o-mini') }}",
        },
        "response_template": "guest_bios/response.json.j2",
    }
    provider_file.write_text(
        yaml.safe_dump(
            provider_config,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def _write_response_template(
    template_dir: Path,
    assistant_content_literal: str,
) -> None:
    """Write the guest-bios response template to Vidai Mock."""
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
    "prompt_tokens": 44,
    "completion_tokens": 18,
    "total_tokens": 62
  }}
}}
""",
        encoding="utf-8",
    )


@given("a Vidai Mock guest-bios server is running")
def vidaimock_server(
    guest_bios_context: GuestBiosBDDContext,
    tmp_path: Path,
) -> None:
    """Start a local Vidai Mock instance with a guest-bios-specific template."""
    provider_dir = tmp_path / "providers"
    template_dir = tmp_path / "templates" / "guest_bios"
    provider_dir.mkdir(parents=True)
    template_dir.mkdir(parents=True)

    _write_provider_config(provider_dir)
    _write_response_template(template_dir, _build_assistant_content_literal())
    start_vidaimock_process(
        guest_bios_context,
        tmp_path,
        label="the guest-bios behavioural test",
    )


@given("a TEI script body and pinned guest profile are prepared")
def prepare_guest_bios_request(guest_bios_context: GuestBiosBDDContext) -> None:
    """Build TEI and a pinned guest profile source for biography generation."""
    guest_bios_context.script_tei_xml = (
        '<TEI xmlns="http://www.tei-c.org/ns/1.0">'
        "<teiHeader><fileDesc><title>Episode 43</title></fileDesc></teiHeader>"
        "<text><body>"
        '<p xml:id="p1">Today we speak with Ada Lovelace.</p>'
        "</body></text>"
        "</TEI>"
    )
    guest_bios_context.sources = (
        GuestBioSource(
            display_name="Ada Lovelace",
            role="Mathematician",
            reference_document_id="doc-ada",
            reference_document_revision_id="rev-ada",
            source_content="Ada wrote notes on the Analytical Engine.",
        ),
    )


@when("the guest-bios generator processes the guest profile")
def run_guest_bios_generation(
    _function_scoped_runner: asyncio.Runner,
    guest_bios_context: GuestBiosBDDContext,
) -> None:
    """Call the guest-bios generator with a live LLM adapter."""

    async def _generate_guest_bios() -> None:
        async with OpenAICompatibleLLMAdapter(
            config=OpenAICompatibleLLMConfig(
                base_url=guest_bios_context.base_url,
                api_key="test-key",
            ),
        ) as adapter:
            recording_port = _RecordingLLMPort(wrapped=adapter)
            config = GuestBiosGeneratorConfig(
                model="gpt-4o-mini",
                provider_operation=LLMProviderOperation.CHAT_COMPLETIONS,
                token_budget=LLMTokenBudget(
                    max_input_tokens=1000,
                    max_output_tokens=500,
                    max_total_tokens=1500,
                ),
            )
            generator = GuestBiosGenerator(llm=recording_port, config=config)

            result = await generator.generate(
                guest_bios_context.script_tei_xml,
                guest_bios_context.sources,
            )
            guest_bios_context.result = result
            guest_bios_context.enriched_tei_xml = enrich_tei_with_guest_bios(
                guest_bios_context.script_tei_xml,
                result,
            )
            assert recording_port.requests, (
                "No LLM requests recorded by _RecordingLLMPort after "
                "GuestBiosGenerator.generate"
            )
            guest_bios_context.request_payload = recording_port.requests[0]

    _run_async_step(_function_scoped_runner, _generate_guest_bios)


@then("the generator returns structured guest biographies")
def assert_guest_bios_result_structure(
    guest_bios_context: GuestBiosBDDContext,
) -> None:
    """Verify the result contains a structured biography tied to its source."""
    result = guest_bios_context.result
    assert result is not None, "Expected a GuestBiosResult, got None."
    assert len(result.entries) == 1, "guest biography entry count must equal one"
    entry = result.entries[0]
    assert entry.display_name == "Ada Lovelace", (
        "guest biography display name must equal Ada Lovelace"
    )
    assert "analytical engines" in entry.bio, (
        "guest biography content must mention analytical engines"
    )
    assert entry.reference_document_revision_id == "rev-ada", (
        "guest biography revision identifier must equal rev-ada"
    )
    assert result.usage.total_tokens == 62, (
        "guest biography usage token count must equal 62"
    )


@then("the guest-bios prompt includes the pinned guest profile content")
def assert_prompt_contains_guest_profile(
    guest_bios_context: GuestBiosBDDContext,
) -> None:
    """Verify the actual outbound request includes the pinned source content."""
    request = guest_bios_context.request_payload
    assert request is not None, "Expected the adapter request to be captured."
    assert "Ada wrote notes on the Analytical Engine" in request.prompt, (
        "Expected collection to contain the value"
    )
    assert "rev-ada" in request.prompt, "Expected collection to contain the value"


@then("the enriched TEI contains a guest-bios body block")
def assert_enriched_tei_contains_guest_bios(
    guest_bios_context: GuestBiosBDDContext,
) -> None:
    """Verify generated biographies use the canonical guest-bios body block."""
    xml = guest_bios_context.enriched_tei_xml
    ada_reference = 'corresp="urn:episodic:reference-document-revision:rev-ada"'
    assert 'type="guest-bios"' in xml, "Expected a guest-bios body block."
    assert ada_reference in xml, "Expected Ada's reference document revision."
    assert "Ada Lovelace wrote about analytical engines." in xml, (
        "Expected Ada's generated biography."
    )
