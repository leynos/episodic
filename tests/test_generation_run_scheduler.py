"""Unit tests for the generation-run scheduler component."""

import asyncio
import dataclasses as dc
import typing as typ
import uuid

import pytest

from episodic.generation.launcher_scheduling import (
    ExecutionOutcome,
    GenerationRunAdmissionError,
    GenerationRunScheduler,
)
from episodic.generation.launcher_support import ClaimToken
from episodic.observability import RecordingTracer

if typ.TYPE_CHECKING:
    import collections.abc as cabc


@dc.dataclass(slots=True)
class _RecordingMetrics:
    """Capture scheduler metrics for assertions."""

    counters: list[tuple[str, dict[str, str]]] = dc.field(default_factory=list)
    values: list[tuple[str, float, dict[str, str]]] = dc.field(default_factory=list)

    def increment_counter(self, name: str, *, labels: cabc.Mapping[str, str]) -> None:
        """Capture one counter increment."""
        self.counters.append((name, dict(labels)))

    def observe_latency_ms(
        self,
        name: str,
        value: float,
        *,
        labels: cabc.Mapping[str, str],
    ) -> None:
        """Accept latency observations outside this component's scope."""
        _ = (name, value, labels)

    def observe_value(
        self,
        name: str,
        value: float,
        *,
        labels: cabc.Mapping[str, str],
    ) -> None:
        """Capture one scalar observation."""
        self.values.append((name, value, dict(labels)))


@dc.dataclass(frozen=True, slots=True)
class _SchedulerRuntime:
    """Live scheduler runtime view backed by recording fakes."""

    metrics: _RecordingMetrics = dc.field(default_factory=_RecordingMetrics)
    tracer: RecordingTracer = dc.field(default_factory=RecordingTracer)
    max_concurrency: int = 4
    max_pending_runs: int = 16
    cancellation_write_timeout_seconds: float = 10.0


@dc.dataclass(slots=True)
class _RecordingExecutor:
    """Executor fake that records admitted runs and returns one outcome."""

    outcome: ExecutionOutcome = dc.field(
        default_factory=lambda: ExecutionOutcome(outcome="completed")
    )
    run_ids: list[uuid.UUID] = dc.field(default_factory=list)

    async def __call__(
        self,
        run_id: uuid.UUID,
        claim: object,
    ) -> ExecutionOutcome:
        """Record the run and return the configured outcome."""
        _ = claim
        self.run_ids.append(run_id)
        return self.outcome


@dc.dataclass(slots=True)
class _RecordingCancellation:
    """Cancellation recorder fake that captures run identifiers.

    It reports the authority a real recorder would: a token naming the run,
    which the scheduler then adopts onto the claim it owns.
    """

    run_ids: list[uuid.UUID] = dc.field(default_factory=list)

    async def record(
        self,
        run_id: uuid.UUID,
        claim: object,
    ) -> ClaimToken:
        """Record one cancellation and report its authority."""
        _ = claim
        self.run_ids += [run_id]
        return ClaimToken(run_id)


class _BlockingExecutor:
    """Executor fake that signals when it starts and then blocks."""

    def __init__(self) -> None:
        """Create the event that signals when execution has started."""
        self.started = asyncio.Event()

    async def __call__(
        self,
        run_id: uuid.UUID,
        claim: object,
    ) -> ExecutionOutcome:
        """Block until the scheduler cancels the task."""
        _ = (run_id, claim)
        self.started.set()
        await asyncio.Event().wait()
        raise AssertionError


def _scheduler(
    executor: cabc.Callable[
        [uuid.UUID, object],
        cabc.Awaitable[ExecutionOutcome],
    ],
    recorder: cabc.Callable[[uuid.UUID, object], cabc.Awaitable[ClaimToken]],
) -> GenerationRunScheduler:
    """Build a scheduler around explicit executor and recorder seams.

    Tests that need a recording tracer or metrics sink, or different limits,
    replace the returned dataclass with ``dataclasses.replace``.

    Returns
    -------
    GenerationRunScheduler
        Scheduler wired to the supplied executor and cancellation recorder.
    """
    return GenerationRunScheduler(
        execute_run=executor,
        record_cancellation=recorder,
    )


@pytest.mark.asyncio
async def test_scheduler_executes_admitted_run_and_records_trace() -> None:
    """An admitted run should execute, drain, and report its outcome."""
    executor = _RecordingExecutor()
    tracer = RecordingTracer()
    scheduler = dc.replace(
        _scheduler(executor, _RecordingCancellation().record),
        runtime=_SchedulerRuntime(tracer=tracer),
    )
    run_id = uuid.uuid7()

    await scheduler.launch(run_id)
    await scheduler.drain()

    assert executor.run_ids == [run_id], executor.run_ids
    assert scheduler.scheduled_run_count == 0, scheduler.scheduled_run_count
    assert tracer.spans[0].name == "generation_run.execute", tracer.spans
    assert tracer.spans[0].attributes == {
        "operation": "generation_run.execute",
        "run_id": str(run_id),
        "outcome": "completed",
    }, tracer.spans[0].attributes
    assert tracer.spans[0].is_completed, tracer.spans[0]


@pytest.mark.asyncio
async def test_scheduler_reports_failed_outcome_category() -> None:
    """A failed outcome should reach the execution span's attributes."""
    executor = _RecordingExecutor(
        ExecutionOutcome(outcome="failed", failure_category="provider.transient")
    )
    tracer = RecordingTracer()
    scheduler = dc.replace(
        _scheduler(executor, _RecordingCancellation().record),
        runtime=_SchedulerRuntime(tracer=tracer),
    )

    await scheduler.launch(uuid.uuid7())
    await scheduler.drain()

    assert tracer.spans[0].attributes["outcome"] == "failed", tracer.spans[0]
    assert tracer.spans[0].attributes["failure_category"] == "provider.transient", (
        tracer.spans[0]
    )


@pytest.mark.asyncio
async def test_scheduler_rejects_admission_beyond_capacity() -> None:
    """Capacity admission should reject work before a task is allocated."""
    executor = _BlockingExecutor()
    metrics = _RecordingMetrics()
    scheduler = dc.replace(
        _scheduler(executor, _RecordingCancellation().record),
        runtime=_SchedulerRuntime(
            metrics=metrics,
            max_concurrency=1,
            max_pending_runs=1,
        ),
    )

    await scheduler.launch(uuid.uuid7())
    await executor.started.wait()
    await scheduler.launch(uuid.uuid7())
    with pytest.raises(GenerationRunAdmissionError, match="capacity"):
        await scheduler.launch(uuid.uuid7())

    assert scheduler.scheduled_run_count == 2, scheduler.scheduled_run_count
    assert (
        "generation_run_admission_rejected_total",
        {"reason": "capacity"},
    ) in metrics.counters, metrics.counters
    assert metrics.values[-1] == ("generation_run_pending_depth", 1.0, {}), (
        metrics.values
    )

    await scheduler.shutdown()


@pytest.mark.asyncio
async def test_scheduler_closes_admission_during_shutdown() -> None:
    """Shutdown should reject new work before it cancels outstanding tasks."""
    metrics = _RecordingMetrics()
    scheduler = dc.replace(
        _scheduler(_RecordingExecutor(), _RecordingCancellation().record),
        runtime=_SchedulerRuntime(metrics=metrics),
    )

    await scheduler.shutdown()
    with pytest.raises(GenerationRunAdmissionError, match="shutdown"):
        await scheduler.launch(uuid.uuid7())

    assert (
        "generation_run_admission_rejected_total",
        {"reason": "shutdown"},
    ) in metrics.counters, metrics.counters


@pytest.mark.asyncio
async def test_scheduler_records_cancellation_once_for_blocked_run() -> None:
    """A run cancelled while executing should be recorded once."""
    executor = _BlockingExecutor()
    recorder = _RecordingCancellation()
    tracer = RecordingTracer()
    scheduler = dc.replace(
        _scheduler(executor, recorder.record),
        runtime=_SchedulerRuntime(tracer=tracer),
    )
    run_id = uuid.uuid7()

    await scheduler.launch(run_id)
    await executor.started.wait()
    await scheduler.shutdown()

    assert recorder.run_ids == [run_id], recorder.run_ids
    assert tracer.spans[0].attributes["outcome"] == "cancelled", tracer.spans[0]
    assert tracer.spans[0].attributes["failure_category"] == "launcher.shutdown", (
        tracer.spans[0]
    )


@pytest.mark.asyncio
async def test_scheduler_records_cancellation_for_task_cancelled_before_start() -> None:
    """A task cancelled before its first step should still be recorded."""
    recorder = _RecordingCancellation()
    scheduler = _scheduler(_RecordingExecutor(), recorder.record)
    run_id = uuid.uuid7()

    await scheduler.launch(run_id)
    await scheduler.shutdown()

    assert recorder.run_ids == [run_id], recorder.run_ids


def test_scheduler_rejects_invalid_limits() -> None:
    """Scheduling limits should be validated at construction time."""
    with pytest.raises(ValueError, match="max_concurrency"):
        dc.replace(
            _scheduler(_RecordingExecutor(), _RecordingCancellation().record),
            runtime=_SchedulerRuntime(max_concurrency=0),
        )
    with pytest.raises(ValueError, match="max_pending_runs"):
        dc.replace(
            _scheduler(_RecordingExecutor(), _RecordingCancellation().record),
            runtime=_SchedulerRuntime(max_pending_runs=-1),
        )
