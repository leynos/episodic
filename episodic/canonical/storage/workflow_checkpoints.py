"""Checkpoint adapter for resumable orchestration workflows.

This adapter implements the orchestration-layer `CheckpointPort` at the
canonical storage boundary. Repeated suspend attempts for the same workflow
step converge on one durable checkpoint, while resume markers remain governed
by the caller's unit-of-work decision. It does not import graph code, LLM
adapters, or Celery concerns.
"""

import typing as typ
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from episodic.canonical.domain import WorkflowCheckpointStatus
from episodic.observability import (
    MetricsPort,
    MonotonicClockPort,
    NoopMetrics,
    PerfCounterClock,
)
from episodic.orchestration import WorkflowCheckpoint
from episodic.orchestration._types import _log_event

from .models import WorkflowCheckpointRecord

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

_METRIC_SAVE_OPERATIONS = "workflow_checkpoint.save_or_reuse.operations"
_METRIC_SAVE_CONFLICTS = "workflow_checkpoint.save_or_reuse.idempotency_conflicts"
_METRIC_SAVE_LATENCY_MS = "workflow_checkpoint.save_or_reuse.latency_ms"
_METRIC_RESUME_OPERATIONS = "workflow_checkpoint.mark_resumed.operations"
_METRIC_RESUME_LATENCY_MS = "workflow_checkpoint.mark_resumed.latency_ms"
_METRIC_RECOVERY_FAILURES = "workflow_checkpoint.recovery_failures"


def _map_checkpoint(record: WorkflowCheckpointRecord) -> WorkflowCheckpoint:
    """Map a SQLAlchemy checkpoint record to the orchestration DTO."""
    return WorkflowCheckpoint(
        checkpoint_id=str(record.id),
        workflow_id=record.workflow_id,
        workflow_type=record.workflow_type,
        step_name=record.step_name,
        idempotency_key=record.idempotency_key,
        payload=record.payload,
        status=str(record.status),
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


class SqlAlchemyWorkflowCheckpointStore:
    """Durable implementation of the orchestration `CheckpointPort`."""

    def __init__(
        self,
        session: "AsyncSession",  # noqa: UP037  # AsyncSession is TYPE_CHECKING-only in __init__.
        *,
        metrics: MetricsPort | None = None,
        clock: MonotonicClockPort | None = None,
    ) -> None:
        self._session = session
        self._metrics = metrics or NoopMetrics()
        self._clock = clock or PerfCounterClock()

    def _record_counter(self, name: str, *, labels: dict[str, str]) -> None:
        """Record a bounded-cardinality counter through the injected metrics port."""
        self._metrics.increment_counter(name, labels=labels)

    def _record_latency(
        self,
        name: str,
        started_at: float,
        *,
        labels: dict[str, str],
    ) -> None:
        """Record elapsed latency through the injected metrics port."""
        elapsed_ms = (self._clock.monotonic_seconds() - started_at) * 1000
        self._metrics.observe_latency_ms(name, elapsed_ms, labels=labels)

    def _record_save_outcome(self, started_at: float, outcome: str) -> None:
        """Record save-or-reuse metrics."""
        labels = {"outcome": outcome}
        self._record_counter(_METRIC_SAVE_OPERATIONS, labels=labels)
        self._record_latency(_METRIC_SAVE_LATENCY_MS, started_at, labels=labels)

    def _record_resume_outcome(self, started_at: float, outcome: str) -> None:
        """Record mark-resumed metrics."""
        labels = {"outcome": outcome}
        self._record_counter(_METRIC_RESUME_OPERATIONS, labels=labels)
        self._record_latency(_METRIC_RESUME_LATENCY_MS, started_at, labels=labels)

    async def get(self, checkpoint_id: str) -> WorkflowCheckpoint | None:
        """Return a checkpoint by identifier."""
        record = await self._session.get(
            WorkflowCheckpointRecord,
            uuid.UUID(checkpoint_id),
        )
        _log_event(
            "debug",
            "sql_checkpoint_store.get",
            checkpoint_id=checkpoint_id,
            found=record is not None,
        )
        if record is None:
            return None
        return _map_checkpoint(record)

    async def get_by_idempotency_key(
        self,
        idempotency_key: str,
    ) -> WorkflowCheckpoint | None:
        """Return the checkpoint for an idempotency key."""
        result = await self._session.execute(
            select(WorkflowCheckpointRecord).where(
                WorkflowCheckpointRecord.idempotency_key == idempotency_key
            )
        )
        record = result.scalar_one_or_none()
        _log_event(
            "debug",
            "sql_checkpoint_store.get_by_idempotency_key",
            idempotency_key=idempotency_key,
            found=record is not None,
        )
        if record is None:
            return None
        return _map_checkpoint(record)

    async def save_or_reuse(self, checkpoint: WorkflowCheckpoint) -> WorkflowCheckpoint:
        """Persist a checkpoint or return the existing record for its key.

        Concurrent callers racing on one idempotency key converge on the first
        checkpoint that reaches durable storage. The returned checkpoint may be
        the new record or a previously persisted record, and callers should use
        its identifier as the authoritative suspend token.

        The method participates in the caller's unit of work and does not make
        the checkpoint durable on its own. If convergence cannot recover the
        existing checkpoint for a conflicting key, the storage failure is
        propagated so the caller can retry or fail the suspend attempt.
        """
        started_at = self._clock.monotonic_seconds()
        record = WorkflowCheckpointRecord(
            id=uuid.UUID(checkpoint.checkpoint_id),
            workflow_id=checkpoint.workflow_id,
            workflow_type=checkpoint.workflow_type,
            step_name=checkpoint.step_name,
            idempotency_key=checkpoint.idempotency_key,
            payload=checkpoint.payload,
            status=WorkflowCheckpointStatus(checkpoint.status),
        )
        try:
            # Keep a duplicate insert attempt isolated from the caller's outer
            # transaction; the public contract above is convergence by key.
            async with self._session.begin_nested():
                self._session.add(record)
                await self._session.flush()
                _log_event(
                    "debug",
                    "sql_checkpoint_store.save_or_reuse.persisted",
                    checkpoint_id=checkpoint.checkpoint_id,
                    idempotency_key=checkpoint.idempotency_key,
                )
                self._record_save_outcome(started_at, "persisted")
        except IntegrityError:
            _log_event(
                "warning",
                "sql_checkpoint_store.save_or_reuse.idempotency_conflict",
                idempotency_key=checkpoint.idempotency_key,
            )
            self._record_counter(
                _METRIC_SAVE_CONFLICTS,
                labels={"outcome": "conflict"},
            )
            existing = await self.get_by_idempotency_key(checkpoint.idempotency_key)
            if existing is not None:
                self._record_save_outcome(started_at, "reused")
                return existing
            _log_event(
                "error",
                "sql_checkpoint_store.save_or_reuse.conflict_missing_checkpoint",
                idempotency_key=checkpoint.idempotency_key,
            )
            self._record_counter(
                _METRIC_RECOVERY_FAILURES,
                labels={
                    "operation": "save_or_reuse",
                    "reason": "conflict_missing_checkpoint",
                },
            )
            self._record_save_outcome(started_at, "recovery_failure")
            raise
        return _map_checkpoint(record)

    async def mark_resumed(self, checkpoint_id: str) -> WorkflowCheckpoint:
        """Mark a checkpoint as resumed and return the updated record.

        The update participates in the caller's unit of work. A committed unit
        of work records the checkpoint as ``resumed``; a rolled-back unit of
        work leaves the checkpoint ``suspended`` and available for a later
        retry.

        Raises
        ------
            ValueError: If ``checkpoint_id`` does not identify a checkpoint.
        """
        started_at = self._clock.monotonic_seconds()
        record = await self._session.get(
            WorkflowCheckpointRecord,
            uuid.UUID(checkpoint_id),
        )
        if record is None:
            self._record_resume_outcome(started_at, "unknown_checkpoint")
            msg = f"unknown checkpoint: {checkpoint_id}"
            raise ValueError(msg)
        record.status = WorkflowCheckpointStatus.RESUMED
        await self._session.flush()
        _log_event(
            "debug",
            "sql_checkpoint_store.mark_resumed",
            checkpoint_id=checkpoint_id,
        )
        self._record_resume_outcome(started_at, "marked")
        await self._session.refresh(record)
        return _map_checkpoint(record)
