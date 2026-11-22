"""Admit, schedule, and shut down background generation-run tasks.

:class:`GenerationRunScheduler` owns bounded task admission, strong task
references, the execution semaphore, and cancellation bookkeeping. It takes
the run executor and the cancellation recorder as narrow injected callables,
so it neither claims a run nor decides how an outcome is persisted. Admission
is checked before an asyncio task is allocated, so a scheduler never exceeds
its configured concurrency and pending-run budget. Shutdown cancels
outstanding tasks, drains them, and records cancellation as a terminal
failure rather than a restart-recoverable state.
"""

import asyncio
import dataclasses as dc
import typing as typ

from episodic.logging import get_logger, log_info
from episodic.observability import (
    NoopTracer,
    NoopValueMetrics,
    TracerPort,
    ValueMetricsPort,
)

if typ.TYPE_CHECKING:
    import collections.abc as cabc
    import uuid

DEFAULT_MAX_CONCURRENCY = 4
DEFAULT_MAX_PENDING_RUNS = 16
_METRIC_ADMISSION_REJECTED = "generation_run_admission_rejected_total"
_METRIC_PENDING_DEPTH = "generation_run_pending_depth"

logger = get_logger(__name__)

type TaskSet = set[asyncio.Task[None]]


class GenerationRunAdmissionError(RuntimeError):
    """Raised when a launcher cannot retain another pending run."""


@dc.dataclass(frozen=True, slots=True)
class ExecutionOutcome:
    """Describe the terminal result of one scheduled run."""

    outcome: str
    failure_category: str | None = None


class SchedulerObservability(typ.Protocol):
    """Live observability ports consulted for each scheduling observation.

    Attributes are properties rather than values so a scheduler that outlives
    its composition root observes the caller's current sinks after the caller
    replaces them.
    """

    @property
    def metrics(self) -> ValueMetricsPort:
        """Sink for admission and pending-depth metrics."""

    @property
    def tracer(self) -> TracerPort:
        """Sink for the per-run execution span."""


@dc.dataclass(frozen=True, slots=True)
class NoopSchedulerObservability:
    """Inert observability view used when the caller supplies none."""

    metrics: ValueMetricsPort = dc.field(default_factory=NoopValueMetrics)
    tracer: TracerPort = dc.field(default_factory=NoopTracer)


@dc.dataclass(slots=True)
class GenerationRunScheduler:
    """Bound task admission and drive scheduled generation-run tasks.

    Attributes
    ----------
    execute_run : cabc.Callable[[uuid.UUID], cabc.Awaitable[ExecutionOutcome]]
        Execute one admitted run under a concurrency permit and report its
        terminal outcome.
    record_cancellation : cabc.Callable[[uuid.UUID], cabc.Awaitable[None]]
        Persist cancellation as a terminal failure for one run.
    observability : SchedulerObservability
        Live view of the metrics and tracer sinks consulted at use time.
    max_concurrency : int
        Maximum runs allowed to execute concurrently.
    max_pending_runs : int
        Maximum runs allowed to wait beyond the execution capacity.
    """

    execute_run: cabc.Callable[[uuid.UUID], cabc.Awaitable[ExecutionOutcome]]
    record_cancellation: cabc.Callable[[uuid.UUID], cabc.Awaitable[None]]
    observability: SchedulerObservability = dc.field(
        default_factory=NoopSchedulerObservability
    )
    max_concurrency: int = DEFAULT_MAX_CONCURRENCY
    max_pending_runs: int = DEFAULT_MAX_PENDING_RUNS
    _tasks: TaskSet = dc.field(default_factory=set, init=False)
    _task_run_ids: dict[asyncio.Task[None], uuid.UUID] = dc.field(
        default_factory=dict,
        init=False,
    )
    _semaphore: asyncio.Semaphore = dc.field(init=False)
    _admitted_run_count: int = dc.field(default=0, init=False)
    _cancelled_run_ids: set[uuid.UUID] = dc.field(default_factory=set, init=False)
    _is_shutting_down: bool = dc.field(default=False, init=False)

    def __post_init__(self) -> None:
        """Validate scheduling limits and allocate the execution semaphore."""
        if self.max_concurrency < 1:
            msg = "max_concurrency must be at least 1."
            raise ValueError(msg)
        if self.max_pending_runs < 0:
            msg = "max_pending_runs must be non-negative."
            raise ValueError(msg)
        self._semaphore = asyncio.Semaphore(self.max_concurrency)

    async def launch(self, run_id: uuid.UUID) -> None:
        """Schedule a background task for one generation run."""
        self._admit()
        try:
            task = asyncio.create_task(
                self._run_task(run_id),
                name=f"generation-run-{run_id}",
            )
        except Exception:
            self._admitted_run_count -= 1
            self._record_pending_depth()
            raise
        self._tasks.add(task)
        self._task_run_ids[task] = run_id
        task.add_done_callback(self._discard_task)
        log_info(logger, "generation_run_launcher.scheduled run_id=%s", run_id)

    async def drain(self) -> None:
        """Wait for all currently scheduled tasks to finish."""
        while self._tasks:
            await asyncio.gather(*tuple(self._tasks), return_exceptions=True)

    @property
    def scheduled_run_count(self) -> int:
        """The number of background runs retained by the scheduler."""
        return len(self._tasks)

    async def shutdown(self) -> None:
        """Cancel and drain all scheduled generation tasks."""
        self._is_shutting_down = True
        cancelled_tasks = tuple(
            (task, self._task_run_ids[task]) for task in self._tasks if not task.done()
        )
        for task, _ in cancelled_tasks:
            task.cancel()
        await self.drain()
        for task, run_id in cancelled_tasks:
            if task.cancelled() and run_id not in self._cancelled_run_ids:
                await asyncio.shield(self.record_cancellation(run_id))
                self._cancelled_run_ids.add(run_id)

    def _discard_task(self, task: asyncio.Task[None]) -> None:
        """Remove finished tasks from the strong-reference registry."""
        self._tasks.discard(task)
        self._task_run_ids.pop(task, None)
        self._admitted_run_count -= 1
        self._record_pending_depth()

    def _admit(self) -> None:
        """Reserve bounded capacity before creating a background task."""
        if self._is_shutting_down:
            self.observability.metrics.increment_counter(
                _METRIC_ADMISSION_REJECTED,
                labels={"reason": "shutdown"},
            )
            msg = "Generation run admission is closed during shutdown."
            raise GenerationRunAdmissionError(msg)
        capacity = self.max_concurrency + self.max_pending_runs
        if self._admitted_run_count >= capacity:
            self.observability.metrics.increment_counter(
                _METRIC_ADMISSION_REJECTED,
                labels={"reason": "capacity"},
            )
            msg = "Generation run admission capacity is exhausted."
            raise GenerationRunAdmissionError(msg)
        self._admitted_run_count += 1
        self._record_pending_depth()

    async def _run_task(self, run_id: uuid.UUID) -> None:
        """Execute one scheduled generation run."""
        with self.observability.tracer.start_span(
            "generation_run.execute",
            attributes={"operation": "generation_run.execute", "run_id": str(run_id)},
        ) as span:
            try:
                async with self._semaphore:
                    outcome = await self.execute_run(run_id)
            except asyncio.CancelledError:
                span.set_attribute("outcome", "cancelled")
                span.set_attribute("failure_category", "launcher.shutdown")
                await asyncio.shield(self.record_cancellation(run_id))
                self._cancelled_run_ids.add(run_id)
                raise
            span.set_attribute("outcome", outcome.outcome)
            if outcome.failure_category is not None:
                span.set_attribute("failure_category", outcome.failure_category)

    def _record_pending_depth(self) -> None:
        """Report bounded work waiting beyond the execution capacity."""
        pending_depth = max(0, self._admitted_run_count - self.max_concurrency)
        self.observability.metrics.observe_value(
            _METRIC_PENDING_DEPTH,
            float(pending_depth),
            labels={},
        )
