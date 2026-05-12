"""SQLAlchemy checkpoint adapter for resumable orchestration workflows.

This adapter implements the orchestration-layer `CheckpointPort` at the
canonical storage boundary. LangGraph nodes hand it typed
`WorkflowCheckpoint` DTOs; the adapter maps those DTOs to the
`workflow_checkpoints` table and relies on the table's unique idempotency key
to make repeated suspend attempts converge on the first persisted checkpoint.
It does not import graph code, LLM adapters, or Celery concerns.
"""

import typing as typ
import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from episodic.canonical.domain import WorkflowCheckpointStatus
from episodic.orchestration import WorkflowCheckpoint
from episodic.orchestration._types import _log_event

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
        status=str(record.status),
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


class SqlAlchemyWorkflowCheckpointStore:
    """Durable SQLAlchemy implementation of the orchestration `CheckpointPort`."""

    def __init__(self, session: "AsyncSession") -> None:  # noqa: UP037
        self._session = session

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
        """Persist a checkpoint or return the existing record for its key."""
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
            async with self._session.begin_nested():
                self._session.add(record)
                await self._session.flush()
                _log_event(
                    "debug",
                    "sql_checkpoint_store.save_or_reuse.persisted",
                    checkpoint_id=checkpoint.checkpoint_id,
                    idempotency_key=checkpoint.idempotency_key,
                )
        except IntegrityError:
            _log_event(
                "warning",
                "sql_checkpoint_store.save_or_reuse.idempotency_conflict",
                idempotency_key=checkpoint.idempotency_key,
            )
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
        record.status = WorkflowCheckpointStatus.RESUMED
        await self._session.flush()
        _log_event(
            "debug",
            "sql_checkpoint_store.mark_resumed",
            checkpoint_id=checkpoint_id,
        )
        await self._session.refresh(record)
        return _map_checkpoint(record)
