"""Unit tests for the structured generation LangGraph seam."""

import asyncio
import dataclasses as dc
import uuid

import pytest

from episodic.llm import LLMUsage
from episodic.orchestration import (
    ActionExecutionResult,
    ActionKind,
    ExecutionPlan,
    GenerationOrchestrationRequest,
    InMemoryCheckpointStore,
    ModelTier,
    PlannedAction,
    PlannerResult,
    ResumeWorkflowCommand,
    WorkflowCheckpoint,
)
from episodic.orchestration.langgraph import (
    GenerationGraphState,
    _execute_node,
    _finish_node,
    _plan_node,
    build_generation_orchestration_graph,
    resume_generation_orchestration,
)


@dc.dataclass(slots=True)
class _FakePlanner:
    """Return one canned planning result."""

    result: PlannerResult

    async def plan(
        self,
        request: GenerationOrchestrationRequest,
    ) -> PlannerResult:
        """Return the canned result after validating the request."""
        assert request.script_tei_xml.startswith("<TEI>"), (
            "expected script_tei_xml to start with '<TEI>', got: "
            f"{request.script_tei_xml!r}"
        )
        return self.result


@dc.dataclass(slots=True)
class _FakeToolExecutor:
    """Return one canned execution result."""

    result: ActionExecutionResult
    calls: list[tuple[PlannedAction, GenerationOrchestrationRequest]] = dc.field(
        default_factory=list
    )

    async def execute(
        self,
        action: PlannedAction,
        context: GenerationOrchestrationRequest,
    ) -> ActionExecutionResult:
        """Return the canned result after validating the action and context."""
        assert action.action_kind is ActionKind.GENERATE_SHOW_NOTES, (
            "expected action_kind to be GENERATE_SHOW_NOTES, got: "
            f"{action.action_kind!r}"
        )
        assert context.correlation_id == "corr-graph", (
            "expected correlation_id to be 'corr-graph', got: "
            f"{context.correlation_id!r}"
        )
        self.calls.append((action, context))
        return self.result


@dc.dataclass(slots=True)
class _FakeResumePort:
    """Return the externally supplied action result for resume tests."""

    calls: list[ResumeWorkflowCommand] = dc.field(default_factory=list)

    async def resume(
        self,
        command: ResumeWorkflowCommand,
    ) -> ActionExecutionResult:
        """Record and return the command result."""
        self.calls.append(command)
        return command.result


def _request() -> GenerationOrchestrationRequest:
    return GenerationOrchestrationRequest(
        correlation_id="corr-graph",
        script_tei_xml="<TEI><text><body><p>Graph request</p></body></text></TEI>",
    )


def _planner_result() -> PlannerResult:
    return PlannerResult(
        plan=ExecutionPlan(
            plan_version="1.0",
            selected_planning_model="gpt-4.1",
            selected_execution_model="gpt-4o-mini",
            steps=(
                PlannedAction(
                    action_id="action-1",
                    action_kind=ActionKind.GENERATE_SHOW_NOTES,
                    rationale="Need show notes.",
                    model_tier=ModelTier.EXECUTION,
                    required_inputs=("script_tei_xml",),
                ),
            ),
        ),
        usage=LLMUsage(input_tokens=15, output_tokens=9, total_tokens=24),
        model="gpt-4.1",
        provider_response_id="planner-1",
        finish_reason="stop",
    )


def _multi_step_planner_result() -> PlannerResult:
    """Return a planner result that exposes unsupported multi-step resume."""
    result = _planner_result()
    first_step = result.plan.steps[0]
    second_step = PlannedAction(
        action_id="action-2",
        action_kind=ActionKind.GENERATE_SHOW_NOTES,
        rationale="Need a second pass.",
        model_tier=ModelTier.EXECUTION,
        required_inputs=("script_tei_xml",),
    )
    return PlannerResult(
        plan=ExecutionPlan(
            plan_version=result.plan.plan_version,
            selected_planning_model=result.plan.selected_planning_model,
            selected_execution_model=result.plan.selected_execution_model,
            steps=(first_step, second_step),
        ),
        usage=result.usage,
        model=result.model,
        provider_response_id=result.provider_response_id,
        finish_reason=result.finish_reason,
    )


def _action_result() -> ActionExecutionResult:
    return ActionExecutionResult(
        action_id="action-1",
        action_kind=ActionKind.GENERATE_SHOW_NOTES,
        model_tier=ModelTier.EXECUTION,
        model="gpt-4o-mini",
        summary="Generated show notes.",
        usage=LLMUsage(input_tokens=10, output_tokens=4, total_tokens=14),
    )


class TestGenerationOrchestrationGraph:
    """Tests for the compiled generation orchestration graph."""

    @pytest.mark.asyncio
    async def test_generation_graph_propagates_plan_and_results(self) -> None:
        """Graph should preserve typed plan and execution results end to end."""
        graph = build_generation_orchestration_graph(
            planner=_FakePlanner(_planner_result()),
            tool_executor=_FakeToolExecutor(_action_result()),
        )

        state = await graph.ainvoke(GenerationGraphState(request=_request()))

        planner_result = state["planner_result"]
        orchestration_result = state["orchestration_result"]
        assert planner_result.plan.selected_planning_model == "gpt-4.1", (
            "expected selected_planning_model to be 'gpt-4.1', got: "
            f"{planner_result.plan.selected_planning_model!r}"
        )
        assert orchestration_result.total_usage.total_tokens == 38, (
            "expected total_usage.total_tokens to be 38, got: "
            f"{orchestration_result.total_usage.total_tokens!r}"
        )
        assert orchestration_result.action_results[0].model == "gpt-4o-mini", (
            "expected first action result model to be 'gpt-4o-mini', got: "
            f"{orchestration_result.action_results[0].model!r}"
        )

    @pytest.mark.asyncio
    async def test_generation_graph_suspends_before_tool_execution(self) -> None:
        """Checkpointing graph should persist a suspend result before execution."""
        checkpoint_store = InMemoryCheckpointStore()
        tool_executor = _FakeToolExecutor(_action_result())
        graph = build_generation_orchestration_graph(
            planner=_FakePlanner(_planner_result()),
            tool_executor=tool_executor,
            checkpoint_port=checkpoint_store,
        )

        state = await graph.ainvoke(GenerationGraphState(request=_request()))

        suspended_result = state["suspended_result"]
        assert suspended_result.workflow_id == "corr-graph"
        assert suspended_result.step_name == "execute"
        checkpoint = await checkpoint_store.get(suspended_result.checkpoint_id)
        assert checkpoint is not None
        assert checkpoint.idempotency_key == suspended_result.idempotency_key
        assert tool_executor.calls == []

    @pytest.mark.asyncio
    async def test_generation_graph_reuses_checkpoint_for_same_step_key(self) -> None:
        """Repeated suspend calls must return the first checkpoint for a step."""
        checkpoint_store = InMemoryCheckpointStore()
        graph = build_generation_orchestration_graph(
            planner=_FakePlanner(_planner_result()),
            tool_executor=_FakeToolExecutor(_action_result()),
            checkpoint_port=checkpoint_store,
        )

        first_state = await graph.ainvoke(GenerationGraphState(request=_request()))
        second_state = await graph.ainvoke(GenerationGraphState(request=_request()))

        assert (
            second_state["suspended_result"].checkpoint_id
            == first_state["suspended_result"].checkpoint_id
        )

    @pytest.mark.asyncio
    async def test_resume_generation_orchestration_finishes_from_checkpoint(
        self,
    ) -> None:
        """Resume should rebuild checkpointed plan state and aggregate a result."""
        checkpoint_store = InMemoryCheckpointStore()
        graph = build_generation_orchestration_graph(
            planner=_FakePlanner(_planner_result()),
            tool_executor=_FakeToolExecutor(_action_result()),
            checkpoint_port=checkpoint_store,
        )
        state = await graph.ainvoke(GenerationGraphState(request=_request()))
        command = ResumeWorkflowCommand(
            checkpoint_id=state["suspended_result"].checkpoint_id,
            result=_action_result(),
        )
        resume_port = _FakeResumePort()

        result = await resume_generation_orchestration(
            checkpoint_port=checkpoint_store,
            resume_port=resume_port,
            command=command,
        )

        assert result.total_usage.total_tokens == 38
        assert result.action_results == (_action_result(),)
        assert resume_port.calls == [command]
        checkpoint = await checkpoint_store.get(command.checkpoint_id)
        assert checkpoint is not None
        assert checkpoint.status == "resumed"

    @pytest.mark.asyncio
    async def test_resume_generation_orchestration_rejects_multi_step_checkpoint(
        self,
    ) -> None:
        """Resume should not silently drop later planned actions."""
        checkpoint_store = InMemoryCheckpointStore()
        graph = build_generation_orchestration_graph(
            planner=_FakePlanner(_multi_step_planner_result()),
            tool_executor=_FakeToolExecutor(_action_result()),
            checkpoint_port=checkpoint_store,
        )
        state = await graph.ainvoke(GenerationGraphState(request=_request()))
        command = ResumeWorkflowCommand(
            checkpoint_id=state["suspended_result"].checkpoint_id,
            result=_action_result(),
        )
        resume_port = _FakeResumePort()

        with pytest.raises(ValueError, match="exactly one planned step"):
            await resume_generation_orchestration(
                checkpoint_port=checkpoint_store,
                resume_port=resume_port,
                command=command,
            )

        assert resume_port.calls == []

    @pytest.mark.asyncio
    async def test_resume_generation_orchestration_raises_on_missing_checkpoint(
        self,
    ) -> None:
        """Resume should fail loudly when the checkpoint identifier is unknown."""
        command = ResumeWorkflowCommand(
            checkpoint_id=str(uuid.uuid4()),
            result=_action_result(),
        )

        with pytest.raises(ValueError, match="unknown checkpoint"):
            await resume_generation_orchestration(
                checkpoint_port=InMemoryCheckpointStore(),
                resume_port=_FakeResumePort(),
                command=command,
            )

    @pytest.mark.asyncio
    async def test_in_memory_checkpoint_store_reuses_concurrent_step_key(
        self,
    ) -> None:
        """Concurrent saves with one step key should return one checkpoint."""
        checkpoint_store = InMemoryCheckpointStore()
        key = "corr-graph:generation_orchestration:execute:action-1:0"
        first = WorkflowCheckpoint(
            checkpoint_id=str(uuid.uuid4()),
            workflow_id="corr-graph",
            workflow_type="generation_orchestration",
            step_name="execute",
            idempotency_key=key,
            payload={"planner_result": {}},
        )
        duplicate = WorkflowCheckpoint(
            checkpoint_id=str(uuid.uuid4()),
            workflow_id="corr-graph",
            workflow_type="generation_orchestration",
            step_name="execute",
            idempotency_key=key,
            payload={"planner_result": {}},
        )

        stored_first, stored_second = await asyncio.gather(
            checkpoint_store.save(first),
            checkpoint_store.save(duplicate),
        )

        assert stored_second.checkpoint_id == stored_first.checkpoint_id


class TestLangGraphNodeValidation:
    """Tests for individual LangGraph node state validation."""

    @pytest.mark.asyncio
    async def test_plan_node_requires_request(self) -> None:
        """Planning node should fail loudly when request state is missing."""
        with pytest.raises(ValueError, match="missing required state value: request"):
            await _plan_node(
                GenerationGraphState(),
                planner=_FakePlanner(_planner_result()),
            )

    @pytest.mark.asyncio
    async def test_execute_node_requires_request(self) -> None:
        """Execution node should fail loudly when request state is missing."""
        with pytest.raises(ValueError, match="missing required state value: request"):
            await _execute_node(
                GenerationGraphState(planner_result=_planner_result()),
                tool_executor=_FakeToolExecutor(_action_result()),
            )

    @pytest.mark.asyncio
    async def test_execute_node_requires_planner_result(self) -> None:
        """Execution node should fail loudly when planning state is missing."""
        with pytest.raises(
            ValueError, match="missing required state value: planner_result"
        ):
            await _execute_node(
                GenerationGraphState(request=_request()),
                tool_executor=_FakeToolExecutor(_action_result()),
            )

    def test_finish_node_requires_request(self) -> None:
        """Finish node should fail loudly when request state is missing."""
        with pytest.raises(ValueError, match="missing required state value: request"):
            _finish_node(
                GenerationGraphState(
                    planner_result=_planner_result(),
                    action_results=(_action_result(),),
                ),
            )

    def test_finish_node_requires_planner_result(self) -> None:
        """Finish node should fail loudly when planning state is missing."""
        with pytest.raises(
            ValueError, match="missing required state value: planner_result"
        ):
            _finish_node(GenerationGraphState(request=_request()))
