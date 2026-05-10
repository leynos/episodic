"""SQLAlchemy checkpoint adapter for resumable orchestration workflows.

This adapter implements the orchestration-layer `CheckpointPort` at the
canonical storage boundary. LangGraph nodes hand it typed
`WorkflowCheckpoint` DTOs; the adapter maps those DTOs to the
`workflow_checkpoints` table and relies on the table's unique idempotency key
to make repeated suspend attempts converge on the first persisted checkpoint.
It does not import graph code, LLM adapters, or Celery concerns.
"""

from __future__ import annotations

import typing as typ
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from episodic.orchestration import WorkflowCheckpoint

from .models import WorkflowCheckpointRecord

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


def _map_checkpoint(record: WorkflowCheckpointRecord) -> WorkflowCheckpoint:
    """Map a SQLAlchemy checkpoint record to the orchestration DTO."""
    return WorkflowCheckpoint(
        checkpoint_id=str(record.id),
        workflow_id=record.workflow_id,
        workflow_type=record.workflow_type,
        step_name=record.step_name,
        idempotency_key=record.idempotency_key,
        payload=record.payload,
        status=record.status,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


class SqlAlchemyWorkflowCheckpointStore:
    """Durable SQLAlchemy implementation of the orchestration `CheckpointPort`."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, checkpoint_id: str) -> WorkflowCheckpoint | None:
        """Return a checkpoint by identifier."""
        record = await self._session.get(
            WorkflowCheckpointRecord,
            uuid.UUID(checkpoint_id),
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
        if record is None:
            return None
        return _map_checkpoint(record)

    async def save(self, checkpoint: WorkflowCheckpoint) -> WorkflowCheckpoint:
        """Persist a checkpoint or return the existing record for its key."""
        record = WorkflowCheckpointRecord(
            id=uuid.UUID(checkpoint.checkpoint_id),
            workflow_id=checkpoint.workflow_id,
            workflow_type=checkpoint.workflow_type,
            step_name=checkpoint.step_name,
            idempotency_key=checkpoint.idempotency_key,
            payload=checkpoint.payload,
            status=checkpoint.status,
        )
        try:
            async with self._session.begin_nested():
                self._session.add(record)
                await self._session.flush()
        except IntegrityError:
            existing = await self.get_by_idempotency_key(checkpoint.idempotency_key)
            if existing is not None:
                return existing
            raise
        return _map_checkpoint(record)

    async def mark_resumed(self, checkpoint_id: str) -> WorkflowCheckpoint:
        """Mark a checkpoint as resumed and return the updated record."""
        record = await self._session.get(
            WorkflowCheckpointRecord,
            uuid.UUID(checkpoint_id),
        )
        if record is None:
            msg = f"unknown checkpoint: {checkpoint_id}"
            raise ValueError(msg)
        record.status = "resumed"
        await self._session.flush()
        await self._session.refresh(record)
        return _map_checkpoint(record)
