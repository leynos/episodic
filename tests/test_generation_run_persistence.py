"""Unit tests for the generation-run persistence component."""

import dataclasses as dc
import typing as typ

import pytest

from episodic.canonical.domain import GenerationRunStatus
from episodic.canonical.generation_quality import QaStatus
from episodic.canonical.generation_run_errors import RunAlreadyTerminal, RunNotFound
from episodic.cost.ports import BillingPeriodKey
from episodic.cost.pricing_snapshot import PricedService
from episodic.generation.launcher_persistence import GenerationRunPersistence
from episodic.generation.launcher_support import Failure
from tests.generation_run_launcher_support import valid_tei
from tests.generation_run_persistence_support import (
    EPISODE_ID,
    NOW,
    RUN_ID,
    RecordingCostRecorder,
    RecordingMetrics,
    claimed_run_value,
    clock,
    persistence,
    result,
    unit_of_work,
)

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from episodic.canonical.unit_of_work_protocols import CanonicalUnitOfWork


@pytest.mark.asyncio
async def test_record_draft_generated_writes_event_with_clock() -> None:
    """The draft-generated event should carry the injected clock's timestamp."""
    uow = unit_of_work()
    run_persistence = persistence(uow)

    await run_persistence.record_draft_generated(RUN_ID, result())

    assert len(uow.generation_runs.events) == 1, uow.generation_runs.events
    run_id, kind, payload, occurred_at = uow.generation_runs.events[0]
    assert (run_id, kind, occurred_at) == (RUN_ID, "draft.generated", NOW), payload
    assert payload["model"] == "gpt-4o-mini", payload
    assert payload["provider_response_id"] == "resp-draft-1", payload
    assert payload["finish_reason"] == "stop", payload
    assert payload["content_hash"] == result().content_hash, payload
    assert payload["usage"] == {
        "input_tokens": 10,
        "output_tokens": 20,
        "total_tokens": 30,
    }, payload
    assert uow.commits == 1, uow.commits
    assert uow.rollbacks == 0, uow.rollbacks


@pytest.mark.asyncio
async def test_persist_success_writes_tei_events_and_status() -> None:
    """A successful run should persist TEI, ordered events, and terminal status."""
    uow = unit_of_work()
    run_persistence = persistence(uow)

    await run_persistence.persist_success(claimed_run_value(), result())

    episode_id, episode_update = uow.episodes.updates[0]
    assert episode_id == EPISODE_ID, episode_id
    assert episode_update.tei_xml == valid_tei(), episode_update
    assert episode_update.qa_status is QaStatus.SKIPPED, episode_update
    assert episode_update.last_generation_run_id == RUN_ID, episode_update
    assert episode_update.expected_revision == 3, episode_update
    assert episode_update.updated_at == NOW, episode_update
    events = uow.generation_runs.events
    assert [kind for _, kind, _, _ in events] == [
        "tei.persisted",
        "run.succeeded",
    ], events
    assert events[0][2]["tei_revision"] == 4, events[0]
    assert events[0][2]["content_hash"] == "sha256:persisted", events[0]
    assert events[0][2]["qa_status"] == QaStatus.SKIPPED.value, events[0]
    assert events[1][2] == {"current_node": "complete"}, events[1]
    status_updates = uow.generation_runs.status_updates
    assert len(status_updates) == 1, status_updates
    update_run_id, status_update = status_updates[0]
    assert update_run_id == RUN_ID, status_update
    assert status_update.status is GenerationRunStatus.SUCCEEDED, status_update
    assert status_update.current_node is None, status_update
    assert status_update.ended_at == NOW, status_update
    assert uow.commits == 1, uow.commits


@pytest.mark.asyncio
async def test_persist_success_records_costs_and_terminal_metric() -> None:
    """A successful run should record provider costs and the terminal metric."""
    uow = unit_of_work()
    recorder = RecordingCostRecorder()
    metrics = RecordingMetrics()
    run_persistence = dc.replace(
        persistence(uow),
        cost_recorder_factory=lambda uow: recorder,
        metrics=metrics,
    )

    await run_persistence.persist_success(claimed_run_value(), result())

    assert len(recorder.pins) == 1, recorder.pins
    pinned_run_id, providers, billing_period = recorder.pins[0]
    assert pinned_run_id == str(RUN_ID), recorder.pins
    assert billing_period == BillingPeriodKey("2026-09"), recorder.pins
    assert len(providers) == 1, providers
    operation = providers[0]
    assert operation.service_kind is PricedService.LLM, operation
    assert operation.provider_name == "openai", operation
    assert operation.model == "gpt-4o-mini", operation
    assert operation.operation == "chat_completions", operation
    assert len(recorder.provider_calls) == 1, recorder.provider_calls
    provider_call = recorder.provider_calls[0]
    assert provider_call.workflow_run_id == str(RUN_ID), provider_call
    assert provider_call.provider_name == "openai", provider_call
    assert provider_call.operation == "chat_completions", provider_call
    assert provider_call.model == "gpt-4o-mini", provider_call
    assert provider_call.billing_period_key == BillingPeriodKey("2026-09"), (
        provider_call
    )
    assert provider_call.recorded_at == NOW.isoformat(), provider_call
    assert recorder.finalized == [(str(RUN_ID), "draft")], recorder.finalized
    assert metrics.counters == [
        (
            "generation_run_terminal_total",
            {"status": GenerationRunStatus.SUCCEEDED.value, "error_category": "none"},
        )
    ], metrics.counters
    assert not metrics.values, metrics.values


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "recorder_factory",
    [
        pytest.param(lambda _uow: None, id="factory_returns_none"),
        pytest.param(None, id="factory_absent"),
    ],
)
async def test_persist_success_skips_cost_recording_when_disabled(
    recorder_factory: cabc.Callable[[object], object] | None,
) -> None:
    """A disabled cost recorder should leave cost writes to a later stage."""
    uow = unit_of_work()
    run_persistence = GenerationRunPersistence(
        uow_factory=lambda: typ.cast("CanonicalUnitOfWork", uow),
        clock=clock,
        cost_recorder_factory=typ.cast("typ.Any", recorder_factory),
    )

    await run_persistence.persist_success(claimed_run_value(), result())

    assert len(uow.episodes.updates) == 1, uow.episodes.updates
    assert [kind for _, kind, _, _ in uow.generation_runs.events] == [
        "tei.persisted",
        "run.succeeded",
    ], uow.generation_runs.events


@pytest.mark.asyncio
async def test_record_failure_writes_failure_events_and_terminal_status() -> None:
    """An invalid-TEI failure should record both events and a failed status."""
    uow = unit_of_work()
    metrics = RecordingMetrics()
    run_persistence = dc.replace(persistence(uow), metrics=metrics)
    failure = Failure(
        message="Invalid TEI.",
        category="tei.invalid",
        should_emit_invalid_tei=True,
    )

    await run_persistence.record_failure(RUN_ID, failure)

    assert [(run_id, kind) for run_id, kind, _, _ in uow.generation_runs.events] == [
        (RUN_ID, "tei.invalid"),
        (RUN_ID, "run.failed"),
    ], uow.generation_runs.events
    events = uow.generation_runs.events
    assert events[0][2] == {"error_category": "tei.invalid"}, events[0]
    assert events[1][2]["error_message"] == "Invalid TEI.", events[1]
    assert events[1][2]["error_category"] == "tei.invalid", events[1]
    assert len(uow.generation_runs.status_updates) == 1, (
        uow.generation_runs.status_updates
    )
    update_run_id, update = uow.generation_runs.status_updates[0]
    assert update_run_id == RUN_ID, update
    assert update.status is GenerationRunStatus.FAILED, update
    assert update.current_node is None, update
    assert update.ended_at == NOW, update
    assert update.error_message == "Invalid TEI.", update
    assert update.error_category == "tei.invalid", update
    assert uow.commits == 1, uow.commits
    assert len(metrics.counters) == 2, metrics.counters
    counter, labels = metrics.counters[0]
    assert counter == "generation_run_terminal_total", metrics.counters
    assert labels["status"] == GenerationRunStatus.FAILED.value, labels
    assert labels["error_category"] == "tei.invalid", labels
    counter, labels = metrics.counters[1]
    assert counter == "generation_run_draft_errors_total", metrics.counters
    assert labels == {"error_category": "tei.invalid"}, labels


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [RunAlreadyTerminal(RUN_ID), RunNotFound(RUN_ID)])
async def test_record_failure_ignores_runs_that_are_not_writable(
    error: Exception,
) -> None:
    """A terminal or missing run should roll back without recording metrics."""
    uow = unit_of_work(status_error=error)
    metrics = RecordingMetrics()
    run_persistence = dc.replace(persistence(uow), metrics=metrics)

    await run_persistence.record_failure(
        RUN_ID,
        Failure(message="Provider failed.", category="provider.transient"),
    )

    assert [kind for _, kind, _, _ in uow.generation_runs.events] == ["run.failed"], (
        uow.generation_runs.events
    )
    assert uow.generation_runs.status_updates == [], uow.generation_runs.status_updates
    assert uow.rollbacks == 1, uow.rollbacks
    assert uow.commits == 0, uow.commits
    assert not metrics.counters, metrics.counters
