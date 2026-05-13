"""Checkpoint adapters for resumable generation orchestration.

The orchestration graph depends on the `CheckpointPort` protocol rather than a
database implementation. This module supplies the lightweight in-memory adapter
used by unit and behavioural tests to exercise the same suspend/resume contract
without SQLAlchemy. It preserves first-write-wins idempotency for workflow-step
keys and injects its clock so tests can make timestamp behaviour deterministic.

`InMemoryCheckpointStore` is intentionally process-local and unbounded. It is
not suitable for production services without eviction, persistence, and
cross-process coordination; production code should use the canonical storage
adapter instead.
"""

import asyncio
import dataclasses as dc
import datetime as dt
import typing as typ

from episodic.orchestration._dto import WorkflowCheckpoint
from episodic.orchestration._types import _log_event

TimeProvider = typ.Callable[[], dt.datetime]


@dc.dataclass(slots=True)
class InMemoryCheckpointStore:
    """In-memory `CheckpointPort` adapter with atomic first-write semantics."""

    time_provider: TimeProvider = lambda: dt.datetime.now(dt.UTC)
    _by_id: dict[str, WorkflowCheckpoint] = dc.field(default_factory=dict)
    _by_key: dict[str, str] = dc.field(default_factory=dict)
    _lock: asyncio.Lock = dc.field(default_factory=asyncio.Lock)

    async def get(self, checkpoint_id: str) -> WorkflowCheckpoint | None:
        """Return a checkpoint by identifier."""
        return self._by_id.get(checkpoint_id)

    async def get_by_idempotency_key(
        self,
        idempotency_key: str,
    ) -> WorkflowCheckpoint | None:
        """Return a checkpoint by its step idempotency key."""
        checkpoint_id = self._by_key.get(idempotency_key)
        if checkpoint_id is None:
            return None
        return self._by_id[checkpoint_id]

    async def save_or_reuse(self, checkpoint: WorkflowCheckpoint) -> WorkflowCheckpoint:
        """Persist a checkpoint, preserving the first record for a key."""
        async with self._lock:
            existing = await self.get_by_idempotency_key(checkpoint.idempotency_key)
            if existing is not None:
                _log_event(
                    "debug",
                    "checkpoint_store.in_memory.save_or_reuse.reuse",
                    checkpoint_id=existing.checkpoint_id,
                    idempotency_key=existing.idempotency_key,
                )
                return existing
            now = self.time_provider()
            stored = WorkflowCheckpoint(
                checkpoint_id=checkpoint.checkpoint_id,
                workflow_id=checkpoint.workflow_id,
                workflow_type=checkpoint.workflow_type,
                step_name=checkpoint.step_name,
                idempotency_key=checkpoint.idempotency_key,
                payload=checkpoint.payload,
                status=checkpoint.status,
                created_at=checkpoint.created_at or now,
                updated_at=checkpoint.updated_at or now,
            )
            self._by_id[stored.checkpoint_id] = stored
            self._by_key[stored.idempotency_key] = stored.checkpoint_id
            _log_event(
                "debug",
                "checkpoint_store.in_memory.save_or_reuse.created",
                checkpoint_id=stored.checkpoint_id,
                idempotency_key=stored.idempotency_key,
            )
            return stored

    async def mark_resumed(self, checkpoint_id: str) -> WorkflowCheckpoint:
        """Mark a stored checkpoint as resumed and return the updated record."""
        async with self._lock:
            existing = self._by_id.get(checkpoint_id)
            if existing is None:
                msg = f"unknown checkpoint: {checkpoint_id}"
                raise ValueError(msg)
            resumed = WorkflowCheckpoint(
                checkpoint_id=existing.checkpoint_id,
                workflow_id=existing.workflow_id,
                workflow_type=existing.workflow_type,
                step_name=existing.step_name,
                idempotency_key=existing.idempotency_key,
                payload=existing.payload,
                status="resumed",
                created_at=existing.created_at,
                updated_at=self.time_provider(),
            )
            self._by_id[checkpoint_id] = resumed
            _log_event(
                "debug",
                "checkpoint_store.in_memory.mark_resumed",
                checkpoint_id=resumed.checkpoint_id,
                idempotency_key=resumed.idempotency_key,
            )
            return resumed
