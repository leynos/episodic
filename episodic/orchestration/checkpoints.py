"""Checkpoint adapters and helpers for resumable generation orchestration."""

import dataclasses as dc
import datetime as dt

from episodic.orchestration._dto import WorkflowCheckpoint


@dc.dataclass(slots=True)
class InMemoryCheckpointStore:
    """In-memory checkpoint adapter for fast orchestration tests."""

    _by_id: dict[str, WorkflowCheckpoint] = dc.field(default_factory=dict)
    _by_key: dict[str, str] = dc.field(default_factory=dict)

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

    async def save(self, checkpoint: WorkflowCheckpoint) -> WorkflowCheckpoint:
        """Persist a checkpoint, preserving the first record for a key."""
        existing = await self.get_by_idempotency_key(checkpoint.idempotency_key)
        if existing is not None:
            return existing
        now = dt.datetime.now(dt.UTC)
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
        return stored
