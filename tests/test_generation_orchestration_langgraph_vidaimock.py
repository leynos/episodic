"""Vidai Mock behavioural coverage for the generation LangGraph path."""

from __future__ import annotations

import dataclasses as dc
import subprocess  # noqa: S404 - required to manage the local Vidai Mock process
import typing as typ

import pytest

from episodic.llm.openai_adapter import (
    OpenAICompatibleLLMAdapter,
    OpenAICompatibleLLMConfig,
)
from episodic.orchestration import (
    ActionKind,
    GenerationGraphState,
    GenerationOrchestrationConfig,
    GenerationOrchestrationRequest,
    ShowNotesToolExecutor,
    StructuredGenerationPlanner,
    build_generation_orchestration_graph,
)
from tests.steps.generation_orchestration_vidaimock import (
    find_free_port,
    start_vidaimock_process,
    write_provider_config,
    write_response_template,
)

if typ.TYPE_CHECKING:
    import collections.abc as cabc
    from pathlib import Path

    from episodic.llm.ports import LLMPort, LLMRequest, LLMResponse


@dc.dataclass(slots=True)
class _VidaiContext:
    """Runtime state for one Vidai Mock-backed graph test."""

    process: subprocess.Popen[str] | None = None
    base_url: str = ""

    def stop(self) -> None:
        """Terminate the local Vidai Mock process if it was started."""
        if self.process is None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)


@dc.dataclass(slots=True)
class _RecordingLLMPort:
    """Capture the actual `LLMRequest` values before delegating."""

    wrapped: LLMPort
    requests: list[LLMRequest] = dc.field(default_factory=list)

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Record and forward the request."""
        self.requests.append(request)
        return await self.wrapped.generate(request)


@pytest.fixture
def vidaimock_context(tmp_path: Path) -> cabc.Iterator[_VidaiContext]:
    """Start the orchestration Vidai Mock server and stop it after the test."""
    provider_dir = tmp_path / "providers"
    template_dir = tmp_path / "templates" / "orchestration"
    provider_dir.mkdir(parents=True)
    template_dir.mkdir(parents=True)

    write_provider_config(provider_dir)
    write_response_template(template_dir)
    context = _VidaiContext()
    start_vidaimock_process(
        typ.cast("typ.Any", context), tmp_path, port=find_free_port()
    )
    try:
        yield context
    finally:
        context.stop()


@pytest.mark.asyncio
async def test_langgraph_plans_executes_and_finishes_with_vidai_mock(
    vidaimock_context: _VidaiContext,
) -> None:
    """The direct graph path completes against a Vidai Mock-backed LLM port."""
    request = GenerationOrchestrationRequest(
        correlation_id="vidai-graph",
        script_tei_xml=(
            "<TEI><text><body><p>Welcome to episode 42.</p>"
            "<p>We discuss the main topic.</p></body></text></TEI>"
        ),
        template_structure={"sections": ["intro", "discussion"]},
    )

    async with OpenAICompatibleLLMAdapter(
        config=OpenAICompatibleLLMConfig(
            base_url=vidaimock_context.base_url,
            api_key="test-key",
        ),
    ) as adapter:
        recording_port = _RecordingLLMPort(wrapped=adapter)
        config = GenerationOrchestrationConfig(
            planning_model="gpt-4.1",
            execution_model="gpt-4o-mini",
        )
        graph = build_generation_orchestration_graph(
            planner=StructuredGenerationPlanner(
                llm=recording_port,
                config=config,
            ),
            tool_executor=ShowNotesToolExecutor(
                llm=recording_port,
                config=config,
            ),
        )

        state = await graph.ainvoke(GenerationGraphState(request=request))

    result = state["orchestration_result"]
    assert result.plan.steps[0].action_kind is ActionKind.GENERATE_SHOW_NOTES
    assert result.action_results[0].show_notes_result is not None
    assert result.action_results[0].show_notes_result.entries[0].topic == "Introduction"
    assert result.total_usage.total_tokens == 81
    assert [call.model for call in recording_port.requests] == [
        "gpt-4.1",
        "gpt-4o-mini",
    ]
