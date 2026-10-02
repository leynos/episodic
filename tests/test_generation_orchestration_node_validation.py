"""Unit tests for generation LangGraph node state validation."""

import collections.abc as cabc  # ruff: ignore[typing-only-standard-library-import] - pytest resolves test annotations at collection

import pytest

from episodic.orchestration import (
    InMemoryCheckpointStore,
    _checkpoint_resume,
    _graph_nodes,
)
from episodic.orchestration.langgraph import (
    GenerationGraphState,
    _execute_node,
    _finish_node,
    _plan_node,
)
from tests.test_generation_orchestration_langgraph import (
    _action_result,
    _FakePlanner,
    _FakeToolExecutor,
    _planner_result,
    _request,
)


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
    @pytest.mark.parametrize(
        ("state_factory", "missing_field"),
        [
            pytest.param(
                lambda: GenerationGraphState(planner_result=_planner_result()),
                "request",
                id="missing-request",
            ),
            pytest.param(
                lambda: GenerationGraphState(request=_request()),
                "planner_result",
                id="missing-planner-result",
            ),
        ],
    )
    async def test_execute_node_requires_required_state(
        self,
        state_factory: cabc.Callable[[], GenerationGraphState],
        missing_field: str,
    ) -> None:
        """Execution rejects each missing required state value independently."""
        state = state_factory()
        with pytest.raises(
            ValueError, match=f"missing required state value: {missing_field}"
        ) as exc_info:
            await _execute_node(
                state,
                tool_executor=_FakeToolExecutor(_action_result()),
                monotonic_clock=lambda: 0.0,
            )

        assert (
            str(exc_info.value) == f"missing required state value: {missing_field}"
        ), "execution should identify the missing required state value"

    @pytest.mark.asyncio
    async def test_execute_node_uses_injected_monotonic_clock(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Action duration logging uses the supplied clock at the node boundary."""
        timestamps = iter((10.0, 10.125))
        logged_events: list[tuple[str, dict[str, object]]] = []

        def record_log_event(_level: str, message: str, **fields: object) -> None:
            logged_events.append((message, fields))

        monkeypatch.setattr(_graph_nodes, "_log_event", record_log_event)
        await _execute_node(
            GenerationGraphState(request=_request(), planner_result=_planner_result()),
            tool_executor=_FakeToolExecutor(_action_result()),
            monotonic_clock=lambda: next(timestamps),
        )

        action_finish = next(
            fields
            for message, fields in logged_events
            if message == "generation_graph.execute_node.action.finish"
        )
        assert action_finish["elapsed_ms"] == pytest.approx(125.0), (
            "elapsed time should be calculated from the injected monotonic clock"
        )

    @pytest.mark.asyncio
    async def test_suspend_logs_checkpoint_payload_validation_failure(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Rejected checkpoint payloads emit identifiers without payload data."""
        events: list[tuple[str, str, dict[str, object]]] = []

        def record_log_event(level: str, message: str, **fields: object) -> None:
            events.append((level, message, fields))

        def invalid_payload(**_: object) -> dict[str, object]:
            return {"bad": object()}

        monkeypatch.setattr(_checkpoint_resume, "_log_event", record_log_event)
        monkeypatch.setattr(
            _checkpoint_resume, "_build_checkpoint_payload", invalid_payload
        )
        state = GenerationGraphState(
            request=_request(),
            planner_result=_planner_result(),
        )

        with pytest.raises(TypeError, match="payload must be JSON-serializable"):
            await _checkpoint_resume._suspend_execute_node(
                state,
                checkpoint_port=InMemoryCheckpointStore(),
            )

        error_events = [event for event in events if event[0] == "error"]
        assert len(error_events) == 1, (
            "payload rejection should emit exactly one error event"
        )
        level, message, fields = error_events[0]
        expected_fields = {
            "correlation_id": "corr-graph",
            "workflow_id": "corr-graph",
            "workflow_type": "generation_orchestration",
            "step_name": "execute",
            "action_id": "action-1",
            "failure_category": "invalid_checkpoint_payload",
        }
        assert level == "error", "payload rejection should be logged at error level"
        assert message == (
            "generation_graph.suspend_execute_node.checkpoint_payload_rejected"
        ), "payload rejection should use its stable event name"
        assert fields == expected_fields, (
            "payload rejection should log only bounded workflow context"
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
