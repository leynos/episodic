"""Unit tests for the structured generation LangGraph seam."""

import asyncio
import uuid

import pytest

from episodic.orchestration import (
    InMemoryCheckpointStore,
    ResumeWorkflowCommand,
    WorkflowCheckpoint,
)
from episodic.orchestration.langgraph import (
    GenerationGraphExtensions,
    GenerationGraphState,
    build_generation_orchestration_graph,
    resume_generation_orchestration,
)
from tests.fixtures.langgraph_orchestration_support import (
    FakePlanner,
    FakeResumePort,
    FakeToolExecutor,
    build_action_result,
    build_multi_step_planner_result,
    build_planner_result,
    build_request,
)


class TestGenerationOrchestrationGraph:
    """Tests for the compiled generation orchestration graph."""

    @pytest.mark.asyncio
    async def test_generation_graph_propagates_plan_and_results(self) -> None:
        """Graph should preserve typed plan and execution results end to end."""
        graph = build_generation_orchestration_graph(
            planner=FakePlanner(build_planner_result()),
            tool_executor=FakeToolExecutor(build_action_result()),
        )

        state = await graph.ainvoke(GenerationGraphState(request=build_request()))

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
        tool_executor = FakeToolExecutor(build_action_result())
        graph = build_generation_orchestration_graph(
            planner=FakePlanner(build_planner_result()),
            tool_executor=tool_executor,
            extensions=GenerationGraphExtensions(checkpoint_port=checkpoint_store),
        )

        state = await graph.ainvoke(GenerationGraphState(request=build_request()))

        suspended_result = state["suspended_result"]
        assert suspended_result.workflow_id == "corr-graph", (
            "suspended workflow_id must equal the request correlation ID"
        )
        assert suspended_result.step_name == "execute", (
            "suspended step_name must identify tool execution"
        )
        checkpoint = await checkpoint_store.get(suspended_result.checkpoint_id)
        assert checkpoint is not None, "suspended checkpoint must be persisted"
        assert checkpoint.idempotency_key == suspended_result.idempotency_key, (
            "persisted checkpoint must retain the suspended idempotency key"
        )
        assert checkpoint.payload["request"] == {"correlation_id": "corr-graph"}, (
            "checkpoint payload must retain the request correlation ID"
        )
        assert not tool_executor.calls, "suspension must occur before executor calls"

    @pytest.mark.asyncio
    async def test_generation_graph_reuses_checkpoint_for_same_step_key(self) -> None:
        """Repeated suspend calls must return the first checkpoint for a step."""
        checkpoint_store = InMemoryCheckpointStore()
        graph = build_generation_orchestration_graph(
            planner=FakePlanner(build_planner_result()),
            tool_executor=FakeToolExecutor(build_action_result()),
            extensions=GenerationGraphExtensions(checkpoint_port=checkpoint_store),
        )

        first_state = await graph.ainvoke(GenerationGraphState(request=build_request()))
        second_state = await graph.ainvoke(
            GenerationGraphState(request=build_request())
        )

        assert (
            second_state["suspended_result"].checkpoint_id
            == first_state["suspended_result"].checkpoint_id
        ), "repeated suspension must reuse the original checkpoint ID"

    @pytest.mark.asyncio
    async def test_resume_generation_orchestration_finishes_from_checkpoint(
        self,
    ) -> None:
        """Resume should rebuild checkpointed plan state and aggregate a result."""
        checkpoint_store = InMemoryCheckpointStore()
        graph = build_generation_orchestration_graph(
            planner=FakePlanner(build_planner_result()),
            tool_executor=FakeToolExecutor(build_action_result()),
            extensions=GenerationGraphExtensions(checkpoint_port=checkpoint_store),
        )
        state = await graph.ainvoke(GenerationGraphState(request=build_request()))
        command = ResumeWorkflowCommand(
            checkpoint_id=state["suspended_result"].checkpoint_id,
            result=build_action_result(),
        )
        resume_port = FakeResumePort()

        result = await resume_generation_orchestration(
            checkpoint_port=checkpoint_store,
            resume_port=resume_port,
            command=command,
        )

        assert result.total_usage.total_tokens == 38, (
            "resumed result must aggregate planner and action token usage"
        )
        assert result.action_results == (build_action_result(),), (
            "resumed result must contain the checkpoint action result"
        )
        assert resume_port.calls == [command], (
            "resume port must receive the resume command exactly once"
        )
        checkpoint = await checkpoint_store.get(command.checkpoint_id)
        assert checkpoint is not None, "resumed checkpoint must still exist"
        assert checkpoint.status == "resumed", (
            "checkpoint status must be marked resumed after execution"
        )

    @pytest.mark.asyncio
    async def test_resume_generation_orchestration_rejects_multi_step_checkpoint(
        self,
    ) -> None:
        """Resume should not silently drop later planned actions."""
        checkpoint_store = InMemoryCheckpointStore()
        graph = build_generation_orchestration_graph(
            planner=FakePlanner(build_multi_step_planner_result()),
            tool_executor=FakeToolExecutor(build_action_result()),
            extensions=GenerationGraphExtensions(checkpoint_port=checkpoint_store),
        )
        with pytest.raises(ValueError, match="exactly one planned step"):
            await graph.ainvoke(GenerationGraphState(request=build_request()))

    @pytest.mark.asyncio
    async def test_resume_generation_orchestration_raises_on_missing_checkpoint(
        self,
    ) -> None:
        """Resume should fail loudly when the checkpoint identifier is unknown."""
        command = ResumeWorkflowCommand(
            checkpoint_id=str(uuid.uuid4()),
            result=build_action_result(),
        )

        with pytest.raises(ValueError, match="unknown checkpoint"):
            await resume_generation_orchestration(
                checkpoint_port=InMemoryCheckpointStore(),
                resume_port=FakeResumePort(),
                command=command,
            )

    @pytest.mark.asyncio
    async def test_resume_generation_orchestration_raises_on_missing_plan_payload(
        self,
    ) -> None:
        """Resume should map malformed checkpoint payloads to TypeError."""
        checkpoint_store = InMemoryCheckpointStore()
        checkpoint = await checkpoint_store.save_or_reuse(
            WorkflowCheckpoint(
                checkpoint_id=str(uuid.uuid4()),
                workflow_id="corr-graph",
                workflow_type="generation_orchestration",
                step_name="execute",
                idempotency_key="corr-graph:generation_orchestration:execute:a1:0",
                payload={},
            )
        )
        command = ResumeWorkflowCommand(
            checkpoint_id=checkpoint.checkpoint_id,
            result=build_action_result(),
        )

        with pytest.raises(TypeError, match="planner_result"):
            await resume_generation_orchestration(
                checkpoint_port=checkpoint_store,
                resume_port=FakeResumePort(),
                command=command,
            )

    @pytest.mark.asyncio
    async def test_resume_generation_orchestration_raises_on_invalid_payload(
        self,
    ) -> None:
        """resume_generation_orchestration raises TypeError for a malformed payload."""
        store = InMemoryCheckpointStore()
        bad_checkpoint = WorkflowCheckpoint(
            checkpoint_id=str(uuid.uuid4()),
            workflow_id="wf-1",
            workflow_type="generation_orchestration",
            step_name="execute",
            idempotency_key="wf-1:generation_orchestration:execute:a1:0",
            payload={"planner_result": {"bad": "shape"}},
        )
        await store.save_or_reuse(bad_checkpoint)

        with pytest.raises(TypeError):
            await resume_generation_orchestration(
                checkpoint_port=store,
                resume_port=FakeResumePort(),
                command=ResumeWorkflowCommand(
                    checkpoint_id=bad_checkpoint.checkpoint_id,
                    result=build_action_result(),
                ),
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
            checkpoint_store.save_or_reuse(first),
            checkpoint_store.save_or_reuse(duplicate),
        )

        assert stored_second.checkpoint_id == stored_first.checkpoint_id, (
            "concurrent saves with one step key must reuse one checkpoint ID"
        )

    @pytest.mark.asyncio
    async def test_in_memory_checkpoint_store_mark_resumed_raises_for_unknown_id(
        self,
    ) -> None:
        """`InMemoryCheckpointStore.mark_resumed` rejects an unknown id."""
        store = InMemoryCheckpointStore()

        with pytest.raises(ValueError, match="unknown checkpoint"):
            await store.mark_resumed(str(uuid.uuid4()))
