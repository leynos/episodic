"""Unit tests for orchestration usage aggregation helpers."""

import json
import typing as typ

from episodic.llm import LLMUsage

if typ.TYPE_CHECKING:
    import pytest

from episodic.orchestration._usage import _sum_usage


def test_sum_usage_derives_total_from_summed_input_and_output_counts() -> None:
    """Verify rollups ignore provider total fields when they disagree."""
    planner_usage = LLMUsage(input_tokens=10, output_tokens=5, total_tokens=99)
    action_usage = LLMUsage(input_tokens=3, output_tokens=7, total_tokens=42)

    total_usage = _sum_usage(planner_usage, action_usage)

    assert total_usage == LLMUsage(input_tokens=13, output_tokens=12, total_tokens=25)


def test_sum_usage_logs_component_and_aggregate_total_mismatches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify inconsistent provider totals emit structured warning events."""
    logged_events: list[tuple[str, str, dict[str, object]]] = []

    def capture_log_event(level: str, message: str, **fields: object) -> None:
        logged_events.append((level, message, dict(fields)))

    monkeypatch.setattr(
        "episodic.orchestration._usage._log_event",
        capture_log_event,
    )

    _sum_usage(
        LLMUsage(input_tokens=10, output_tokens=5, total_tokens=99),
        LLMUsage(input_tokens=3, output_tokens=7, total_tokens=42),
    )

    assert [event[1] for event in logged_events] == [
        "orchestration.usage_sum.component_total_mismatch",
        "orchestration.usage_sum.component_total_mismatch",
        "orchestration.usage_sum.aggregate_total_mismatch",
    ]
    assert all(event[0] == "warning" for event in logged_events)
    aggregate_fields = logged_events[-1][2]
    assert aggregate_fields == {
        "reported_total_tokens": 141,
        "derived_total_tokens": 25,
        "summed_input_tokens": 13,
        "summed_output_tokens": 12,
    }


def test_sum_usage_skips_logging_when_provider_totals_are_consistent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify consistent provider totals do not emit mismatch warnings."""
    logged_events: list[str] = []

    def capture_log_event(level: str, message: str, **fields: object) -> None:
        logged_events.append(message)
        if fields:
            logged_events.append(json.dumps(fields, sort_keys=True))

    monkeypatch.setattr(
        "episodic.orchestration._usage._log_event",
        capture_log_event,
    )

    total_usage = _sum_usage(
        LLMUsage(input_tokens=10, output_tokens=5, total_tokens=15),
        LLMUsage(input_tokens=3, output_tokens=7, total_tokens=10),
    )

    assert total_usage == LLMUsage(input_tokens=13, output_tokens=12, total_tokens=25)
    assert not logged_events
