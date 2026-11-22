"""Unit tests for the generation-run persistence component."""

import typing as typ

import pytest

from episodic.canonical.domain import GenerationRunStatus
from episodic.canonical.generation_quality import QaStatus
from episodic.canonical.generation_run_errors import RunAlreadyTerminal, RunNotFound
from episodic.canonical.generation_run_ports import GenerationRunStatusUpdate
from episodic.cost.ports import BillingPeriodKey
from episodic.cost.pricing_snapshot import PricedService
from episodic.cost.recorder import CostProviderOperation
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

    assert uow.generation_runs.events == [
        (
            RUN_ID,
            "draft.generated",
            {
                "model": "gpt-4o-mini",
                "provider_response_id": "resp-draft-1",
                "finish_reason": "stop",
                "content_hash": result().content_hash,
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 20,
                    "total_tokens": 30,
                },
            },
            NOW,
        )
    ], uow.generation_runs.events
    assert uow.commits == 1, uow.commits
    assert uow.rollbacks == 0, uow.rollbacks


@pytest.mark.asyncio
async def test_persist_success_writes_tei_events_costs_and_status() -> None:
    """A successful run should persist TEI, ordered events, costs, and status."""
    uow = unit_of_work()
    recorder = RecordingCostRecorder()
    metrics = RecordingMetrics()
    run_persistence = persistence(uow, recorder=recorder, metrics=metrics)

    await run_persistence.persist_success(claimed_run_value(), result())

    episode_id, update = uow.episodes.updates[0]
    assert episode_id == EPISODE_ID, episode_id
    assert update.tei_xml == valid_tei(), update
    assert update.qa_status is QaStatus.SKIPPED, update
    assert update.last_generation_run_id == RUN_ID, update
    assert update.expected_revision == 3, update
    assert update.updated_at == NOW, update
    assert [(run_id, kind) for run_id, kind, _, _ in uow.generation_runs.events] == [
        (RUN_ID, "tei.persisted"),
        (RUN_ID, "run.succeeded"),
    ], uow.generation_runs.events
    assert uow.generation_runs.events[0][2] == {
        "tei_revision": 4,
        "content_hash": "sha256:persisted",
        "qa_status": QaStatus.SKIPPED.value,
    }, uow.generation_runs.events[0]
    assert uow.generation_runs.events[1][2] == {"current_node": "complete"}, (
        uow.generation_runs.events[1]
    )
    assert uow.generation_runs.status_updates == [
        (
            RUN_ID,
            GenerationRunStatusUpdate(
                status=GenerationRunStatus.SUCCEEDED,
                current_node=None,
                ended_at=NOW,
            ),
        )
    ], uow.generation_runs.status_updates
    assert uow.commits == 1, uow.commits
    assert recorder.pins == [
        (
            str(RUN_ID),
            (
                CostProviderOperation(
                    service_kind=PricedService.LLM,
                    provider_name="openai",
                    model="gpt-4o-mini",
                    operation="chat_completions",
                ),
            ),
            BillingPeriodKey("2026-09"),
        )
    ], recorder.pins
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
    assert metrics.values == [], metrics.values


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
    run_persistence = persistence(uow, metrics=metrics)
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
    assert uow.generation_runs.events[0][2] == {"error_category": "tei.invalid"}, (
        uow.generation_runs.events[0]
    )
    assert uow.generation_runs.events[1][2] == {
        "error_message": "Invalid TEI.",
        "error_category": "tei.invalid",
    }, uow.generation_runs.events[1]
    assert uow.generation_runs.status_updates == [
        (
            RUN_ID,
            GenerationRunStatusUpdate(
                status=GenerationRunStatus.FAILED,
                current_node=None,
                ended_at=NOW,
                error_message="Invalid TEI.",
                error_category="tei.invalid",
            ),
        )
    ], uow.generation_runs.status_updates
    assert uow.commits == 1, uow.commits
    assert metrics.counters == [
        (
            "generation_run_terminal_total",
            {
                "status": GenerationRunStatus.FAILED.value,
                "error_category": "tei.invalid",
            },
        ),
        (
            "generation_run_draft_errors_total",
            {"error_category": "tei.invalid"},
        ),
    ], metrics.counters


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [RunAlreadyTerminal(RUN_ID), RunNotFound(RUN_ID)])
async def test_record_failure_ignores_runs_that_are_not_writable(
    error: Exception,
) -> None:
    """A terminal or missing run should roll back without recording metrics."""
    uow = unit_of_work(status_error=error)
    metrics = RecordingMetrics()
    run_persistence = persistence(uow, metrics=metrics)

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
    assert metrics.counters == [], metrics.counters
