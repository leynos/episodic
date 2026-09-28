"""Unit tests for generation LangGraph node state validation."""

import pytest

from episodic.orchestration import _graph_nodes
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
    async def test_execute_node_requires_request(self) -> None:
        """Execution node should fail loudly when request state is missing."""
        with pytest.raises(ValueError, match="missing required state value: request"):
            await _execute_node(
                GenerationGraphState(planner_result=_planner_result()),
                tool_executor=_FakeToolExecutor(_action_result()),
                monotonic_clock=lambda: 0.0,
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
                monotonic_clock=lambda: 0.0,
            )

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
        assert action_finish["elapsed_ms"] == 125.0, (
            "elapsed time should be calculated from the injected monotonic clock"
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
