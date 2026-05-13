"""SQLAlchemy models for orchestration workflow checkpoints."""

import datetime as dt  # noqa: TC003  # SQLAlchemy evaluates annotations at runtime.
import uuid  # noqa: TC003  # SQLAlchemy evaluates annotations at runtime.

import sqlalchemy as sa
from sqlalchemy import orm
from sqlalchemy.dialects import postgresql

from episodic.canonical.domain import WorkflowCheckpointStatus

from .models_base import WORKFLOW_CHECKPOINT_STATUS, Base


class WorkflowCheckpointRecord(Base):
    """SQLAlchemy model for resumable orchestration checkpoints."""

    __tablename__ = "workflow_checkpoints"

    id: orm.Mapped[uuid.UUID] = orm.mapped_column(
        postgresql.UUID(as_uuid=True),
        primary_key=True,
    )
    workflow_id: orm.Mapped[str] = orm.mapped_column(
        sa.String(160),
        nullable=False,
        index=True,
    )
    workflow_type: orm.Mapped[str] = orm.mapped_column(sa.String(120), nullable=False)
    step_name: orm.Mapped[str] = orm.mapped_column(sa.String(120), nullable=False)
    idempotency_key: orm.Mapped[str] = orm.mapped_column(
        sa.String(512),
        nullable=False,
        unique=True,
    )
    payload: orm.Mapped[dict[str, object]] = orm.mapped_column(
        postgresql.JSONB,
        nullable=False,
    )
    status: orm.Mapped[WorkflowCheckpointStatus] = orm.mapped_column(
        WORKFLOW_CHECKPOINT_STATUS,
        nullable=False,
        server_default=WorkflowCheckpointStatus.SUSPENDED.value,
    )
    created_at: orm.Mapped[dt.datetime] = orm.mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )
    updated_at: orm.Mapped[dt.datetime] = orm.mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )
