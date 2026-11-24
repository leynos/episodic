"""Bounded shutdown and unbounded normal drain for the run scheduler.

Shutdown must not hang on a stalled cancellation write, a stalled
unit-of-work exit, or a run that outlives the deadline. A normal drain has
the opposite contract: it returns only once the scheduled work has finished.
"""

import asyncio
import dataclasses as dc
import typing as typ
import uuid

import pytest

from episodic.generation.launcher_scheduling import (
    ExecutionOutcome,
    GenerationRunScheduler,
)
from tests.test_generation_run_scheduler import (
    _BlockingExecutor,
    _RecordingCancellation,
    _RecordingMetrics,
    _scheduler,
    _SchedulerRuntime,
)


@dc.dataclass(slots=True)
class _StalledCancellation:
    """Cancellation recorder fake whose write never completes."""

    started: asyncio.Event = dc.field(default_factory=asyncio.Event)
    release: asyncio.Event = dc.field(default_factory=asyncio.Event)
    calls: int = 0

    async def record(self, run_id: uuid.UUID, claim: object) -> bool:
        """Signal entry, then block until the test releases the write."""
        _ = (run_id, claim)
        self.calls += 1
        self.started.set()
        await self.release.wait()
        return True


@pytest.mark.asyncio
async def test_shutdown_abandons_a_stalled_cancellation_write() -> None:
    """A stalled cancellation write cannot hold shutdown open past its bound."""
    recorder = _StalledCancellation()
    metrics = _RecordingMetrics()
    scheduler = dc.replace(
        _scheduler(_BlockingExecutor(), recorder.record),
        runtime=_SchedulerRuntime(
            metrics=metrics,
            cancellation_write_timeout_seconds=0.2,
        ),
    )
    executor = typ.cast("_BlockingExecutor", scheduler.execute_run)

    await scheduler.launch(uuid.uuid4())
    await asyncio.wait_for(executor.started.wait(), timeout=5)
    shutdown = asyncio.create_task(scheduler.shutdown())
    await asyncio.wait_for(recorder.started.wait(), timeout=5)
    await asyncio.wait_for(shutdown, timeout=5)

    timeouts = [
        name
        for name, _labels in metrics.counters
        if name == "generation_run_cancellation_write_timeouts_total"
    ]
    assert timeouts, f"the abandoned write must be counted: {metrics.counters}"
    assert not scheduler.scheduled_run_count, "the run task must be drained"

    recorder.release.set()


class _StubbornExecutor:
    """Executor fake that keeps blocking after its cancellation arrives."""

    def __init__(self) -> None:
        """Create the event that signals when execution has started."""
        self.started = asyncio.Event()

    async def __call__(
        self,
        run_id: uuid.UUID,
        claim: object,
    ) -> ExecutionOutcome:
        """Ignore cancellation, simulating a stalled unit-of-work exit."""
        _ = (run_id, claim)
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            await asyncio.Event().wait()
        raise AssertionError


@pytest.mark.asyncio
async def test_shutdown_abandons_a_stalled_run_task() -> None:
    """A run task that never finishes cannot hold shutdown open."""
    metrics = _RecordingMetrics()
    scheduler = dc.replace(
        _scheduler(_StubbornExecutor(), _RecordingCancellation().record),
        runtime=_SchedulerRuntime(
            metrics=metrics,
            cancellation_write_timeout_seconds=0.2,
        ),
    )
    executor = typ.cast("_StubbornExecutor", scheduler.execute_run)

    await scheduler.launch(uuid.uuid4())
    await asyncio.wait_for(executor.started.wait(), timeout=5)
    await asyncio.wait_for(scheduler.shutdown(), timeout=5)

    timeouts = [
        name
        for name, _labels in metrics.counters
        if name == "generation_run_shutdown_task_timeouts_total"
    ]
    assert timeouts, f"the stalled task must be counted: {metrics.counters}"


class _SlowExecutor:
    """Executor fake that finishes after a delay longer than the deadline."""

    def __init__(self, delay: float) -> None:
        """Store how long the run should take."""
        self._delay = delay
        self.finished = False

    async def __call__(
        self,
        run_id: uuid.UUID,
        claim: object,
    ) -> ExecutionOutcome:
        """Sleep past the deadline, then report completion."""
        _ = (run_id, claim)
        await asyncio.sleep(self._delay)
        self.finished = True
        return ExecutionOutcome(outcome="completed")


@pytest.mark.asyncio
async def test_normal_drain_waits_past_the_shutdown_deadline() -> None:
    """A normal drain waits for a run that outlives the shutdown deadline."""
    executor = _SlowExecutor(delay=0.5)
    scheduler = dc.replace(
        _scheduler(executor, _RecordingCancellation().record),
        runtime=_SchedulerRuntime(cancellation_write_timeout_seconds=0.05),
    )

    await scheduler.launch(uuid.uuid4())
    await scheduler.drain()

    assert executor.finished, "drain returned before the run finished"
    assert not scheduler.scheduled_run_count, scheduler.scheduled_run_count
    assert not metrics_timeouts(scheduler), "normal drain must not count a timeout"


def metrics_timeouts(scheduler: GenerationRunScheduler) -> list[str]:
    """Return the shutdown-timeout counters recorded on a scheduler."""
    metrics = typ.cast("_SchedulerRuntime", scheduler.runtime).metrics
    return [
        name for name, _labels in metrics.counters if name.endswith("_timeouts_total")
    ]


class _AdmittingExecutor:
    """Executor fake that admits a second run while the first is draining."""

    def __init__(self, scheduler_ref: list[GenerationRunScheduler]) -> None:
        """Store the cell that will receive the scheduler."""
        self._ref = scheduler_ref
        self.started = asyncio.Event()
        self.second_started = asyncio.Event()
        self.calls = 0

    async def __call__(
        self,
        run_id: uuid.UUID,
        claim: object,
    ) -> ExecutionOutcome:
        """Start the sibling run once, then finish."""
        _ = (run_id, claim)
        self.calls += 1
        if self.calls == 1:
            self.started.set()
            await asyncio.sleep(0.05)
            await self._ref[0].launch(uuid.uuid4())
            return ExecutionOutcome(outcome="completed")
        self.second_started.set()
        await asyncio.sleep(0.05)
        return ExecutionOutcome(outcome="completed")


@pytest.mark.asyncio
async def test_normal_drain_covers_a_run_admitted_while_waiting() -> None:
    """A run admitted during a normal drain is still awaited by it."""
    ref: list[GenerationRunScheduler] = []
    executor = _AdmittingExecutor(ref)
    scheduler = dc.replace(
        _scheduler(executor, _RecordingCancellation().record),
        runtime=_SchedulerRuntime(),
    )
    ref.append(scheduler)

    await scheduler.launch(uuid.uuid4())
    await scheduler.drain()

    assert executor.second_started.is_set(), "the second run never started"
    assert executor.calls == 2, executor.calls
    assert not scheduler.scheduled_run_count, scheduler.scheduled_run_count
