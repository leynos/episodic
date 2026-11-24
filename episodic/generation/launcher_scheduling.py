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

from episodic.generation.launcher_support import RunClaim
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
#: How long shutdown waits for one cancellation write before giving up on it.
#: A write that outlives this is abandoned, not cancelled: it stays shielded so
#: it can still land, and lease reclamation covers the run if it never does.
DEFAULT_CANCELLATION_WRITE_TIMEOUT_SECONDS = 10.0
_METRIC_ADMISSION_REJECTED = "generation_run_admission_rejected_total"
_METRIC_PENDING_DEPTH = "generation_run_pending_depth"
_METRIC_CANCELLATION_TIMEOUT = "generation_run_cancellation_write_timeouts_total"
_METRIC_TASK_TIMEOUT = "generation_run_shutdown_task_timeouts_total"

logger = get_logger(__name__)

type TaskSet = set[asyncio.Task[None]]


class GenerationRunAdmissionError(RuntimeError):
    """Raised when a launcher cannot retain another pending run."""


@dc.dataclass(frozen=True, slots=True)
class ExecutionOutcome:
    """Describe the terminal result of one scheduled run."""

    outcome: str
    failure_category: str | None = None
    quality_branch: str | None = None
    terminal: str | None = None


class SchedulerRuntimeView(typ.Protocol):
    """Live configuration and observability consulted at use time.

    Attributes are properties rather than values so a scheduler that outlives
    its composition root observes the caller's current sinks and admission
    limits after the caller replaces them. The execution semaphore is sized
    once from the limits in force at construction, matching the pre-split
    launcher, which never resized it.
    """

    @property
    def metrics(self) -> ValueMetricsPort:
        """Sink for admission and pending-depth metrics."""

    @property
    def tracer(self) -> TracerPort:
        """Sink for the per-run execution span."""

    @property
    def max_concurrency(self) -> int:
        """Maximum runs allowed to execute concurrently."""

    @property
    def max_pending_runs(self) -> int:
        """Maximum runs allowed to wait beyond the execution capacity."""

    @property
    def cancellation_write_timeout_seconds(self) -> float:
        """Maximum time shutdown waits for one cancellation write."""


@dc.dataclass(frozen=True, slots=True)
class NoopSchedulerRuntimeView:
    """Inert runtime view used when the caller supplies none."""

    metrics: ValueMetricsPort = dc.field(default_factory=NoopValueMetrics)
    tracer: TracerPort = dc.field(default_factory=NoopTracer)
    max_concurrency: int = DEFAULT_MAX_CONCURRENCY
    max_pending_runs: int = DEFAULT_MAX_PENDING_RUNS
    cancellation_write_timeout_seconds: float = (
        DEFAULT_CANCELLATION_WRITE_TIMEOUT_SECONDS
    )


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
    runtime : SchedulerRuntimeView
        Live view of the metrics, tracer and admission limits.
    """

    execute_run: cabc.Callable[[uuid.UUID, RunClaim], cabc.Awaitable[ExecutionOutcome]]
    record_cancellation: cabc.Callable[[uuid.UUID, RunClaim], cabc.Awaitable[bool]]
    runtime: SchedulerRuntimeView = dc.field(default_factory=NoopSchedulerRuntimeView)
    _tasks: TaskSet = dc.field(default_factory=set, init=False)
    _task_run_ids: dict[asyncio.Task[None], uuid.UUID] = dc.field(
        default_factory=dict,
        init=False,
    )
    _semaphore: asyncio.Semaphore = dc.field(init=False)
    _admitted_run_count: int = dc.field(default=0, init=False)
    _cancelled_run_ids: set[uuid.UUID] = dc.field(default_factory=set, init=False)
    _pending_cancellation_ids: set[uuid.UUID] = dc.field(
        default_factory=set,
        init=False,
    )
    _cancellation_tasks: set[asyncio.Task[bool]] = dc.field(
        default_factory=set,
        init=False,
    )
    _is_shutting_down: bool = dc.field(default=False, init=False)

    def __post_init__(self) -> None:
        """Validate scheduling limits and allocate the execution semaphore."""
        if self.runtime.max_concurrency < 1:
            msg = "max_concurrency must be at least 1."
            raise ValueError(msg)
        if self.runtime.max_pending_runs < 0:
            msg = "max_pending_runs must be non-negative."
            raise ValueError(msg)
        self._semaphore = asyncio.Semaphore(self.runtime.max_concurrency)

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
        """Wait for scheduled tasks and cancellation writes.

        During normal operation every wait is unbounded, matching the
        documented contract that ``drain`` returns only once the work has
        finished. Shutdown bounds both waits by
        ``cancellation_write_timeout_seconds``, because a stalled database
        call or unit-of-work exit must not hold process shutdown open.
        """
        deadline = (
            self.runtime.cancellation_write_timeout_seconds
            if self._is_shutting_down
            else None
        )
        if self._tasks:
            if deadline is None:
                await asyncio.gather(*tuple(self._tasks), return_exceptions=True)
            else:
                _done, still_pending = await asyncio.wait(
                    tuple(self._tasks),
                    timeout=deadline,
                )
                if still_pending:
                    log_info(
                        logger,
                        "generation_run_launcher.shutdown_task_timeout pending=%s",
                        len(still_pending),
                    )
                    self.runtime.metrics.increment_counter(
                        _METRIC_TASK_TIMEOUT,
                        labels={},
                    )
        await self._drain_cancellation_writes(deadline=deadline)

    async def _drain_cancellation_writes(self, *, deadline: float | None) -> None:
        """Await pending cancellation writes, bounded during shutdown only.

        A write that misses the deadline is abandoned, not cancelled: it stays
        shielded so it can still land, and the run it covers falls back to
        lease reclamation. Each miss increments a counter so an operator can
        see that shutdown did not confirm the write.
        """
        pending = tuple(self._cancellation_tasks)
        if not pending:
            return
        if deadline is None:
            await asyncio.gather(*pending, return_exceptions=True)
            return
        _done, still_pending = await asyncio.wait(pending, timeout=deadline)
        if still_pending:
            self._report_cancellation_timeout(None)

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
            if task.cancelled() and run_id not in self._pending_cancellation_ids:
                await self.record_cancellation_owned(run_id, RunClaim())

    def _discard_task(self, task: asyncio.Task[None]) -> None:
        """Remove finished tasks from the strong-reference registry."""
        self._tasks.discard(task)
        self._task_run_ids.pop(task, None)
        self._admitted_run_count -= 1
        self._record_pending_depth()

    def _admit(self) -> None:
        """Reserve bounded capacity before creating a background task."""
        if self._is_shutting_down:
            self.runtime.metrics.increment_counter(
                _METRIC_ADMISSION_REJECTED,
                labels={"reason": "shutdown"},
            )
            msg = "Generation run admission is closed during shutdown."
            raise GenerationRunAdmissionError(msg)
        capacity = self.runtime.max_concurrency + self.runtime.max_pending_runs
        if self._admitted_run_count >= capacity:
            self.runtime.metrics.increment_counter(
                _METRIC_ADMISSION_REJECTED,
                labels={"reason": "capacity"},
            )
            msg = "Generation run admission capacity is exhausted."
            raise GenerationRunAdmissionError(msg)
        self._admitted_run_count += 1
        self._record_pending_depth()

    async def _run_task(self, run_id: uuid.UUID) -> None:
        """Execute one scheduled generation run."""
        with self.runtime.tracer.start_span(
            "generation_run.execute",
            attributes={"operation": "generation_run.execute", "run_id": str(run_id)},
        ) as span:
            claim = RunClaim()
            try:
                async with self._semaphore:
                    outcome = await self.execute_run(run_id, claim)
            except asyncio.CancelledError:
                span.set_attribute("outcome", "cancelled")
                span.set_attribute("failure_category", "launcher.shutdown")
                await self.record_cancellation_owned(run_id, claim)
                raise
            span.set_attribute("outcome", outcome.outcome)
            if outcome.failure_category is not None:
                span.set_attribute("failure_category", outcome.failure_category)
            if outcome.quality_branch is not None:
                span.set_attribute("quality_branch", outcome.quality_branch)
            if outcome.terminal is not None:
                span.set_attribute("terminal", outcome.terminal)

    async def record_cancellation_owned(
        self,
        run_id: uuid.UUID,
        claim: RunClaim,
    ) -> None:
        """Record a cancellation from a task named for the run (INV-9)."""
        if run_id in self._cancelled_run_ids:
            return
        if claim.token is None and run_id in self._pending_cancellation_ids:
            return
        self._pending_cancellation_ids.add(run_id)
        write = asyncio.create_task(
            self._record_cancellation_write(run_id, claim),
            name=f"generation-run-{run_id}",
        )
        self._cancellation_tasks.add(write)

        def _done(task: asyncio.Task[bool]) -> None:
            """Forget a finished cancellation write."""
            self._cancellation_tasks.discard(task)
            self._pending_cancellation_ids.discard(run_id)

        write.add_done_callback(_done)
        try:
            recorded = await asyncio.wait_for(
                asyncio.shield(write),
                timeout=self.runtime.cancellation_write_timeout_seconds,
            )
        except TimeoutError:
            self._report_cancellation_timeout(run_id)
            return
        if recorded:
            self._cancelled_run_ids.add(run_id)

    def _report_cancellation_timeout(self, run_id: uuid.UUID | None) -> None:
        """Record that a cancellation write missed its deadline.

        The write is left running: it is shielded, so it can still land, and
        the run's durable claim and lease let reclamation cover it otherwise.
        """
        log_info(
            logger,
            "generation_run_launcher.cancellation_write_timeout run_id=%s",
            run_id,
        )
        self.runtime.metrics.increment_counter(
            _METRIC_CANCELLATION_TIMEOUT,
            labels={},
        )

    async def _record_cancellation_write(
        self,
        run_id: uuid.UUID,
        claim: RunClaim,
    ) -> bool:
        """Perform one cancellation write and report whether it landed."""
        return await self.record_cancellation(run_id, claim)

    def _record_pending_depth(self) -> None:
        """Report bounded work waiting beyond the execution capacity."""
        pending_depth = max(0, self._admitted_run_count - self.runtime.max_concurrency)
        self.runtime.metrics.observe_value(
            _METRIC_PENDING_DEPTH,
            float(pending_depth),
            labels={},
        )
