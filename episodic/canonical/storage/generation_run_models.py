"""SQLAlchemy models for durable generation runs and event logs."""

import datetime as dt  # noqa: TC003  # SQLAlchemy evaluates annotations at runtime.
import uuid  # noqa: TC003  # SQLAlchemy evaluates annotations at runtime.

import sqlalchemy as sa
from sqlalchemy import orm
from sqlalchemy.dialects import postgresql

from episodic.canonical.domain import GenerationRunStatus, JsonMapping  # noqa: TC001
from episodic.canonical.generation_quality import (  # noqa: TC001
    QaStatus,
    QualityMode,
)

from .models_base import GENERATION_RUN_STATUS, QA_STATUS, QUALITY_MODE, Base


class GenerationRunRecord(Base):
    """SQLAlchemy model for first-class generation-run resources."""

    __tablename__ = "generation_runs"

    id: orm.Mapped[uuid.UUID] = orm.mapped_column(
        postgresql.UUID(as_uuid=True),
        primary_key=True,
    )
    episode_id: orm.Mapped[uuid.UUID] = orm.mapped_column(
        postgresql.UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    source_bundle_id: orm.Mapped[uuid.UUID] = orm.mapped_column(
        postgresql.UUID(as_uuid=True),
        nullable=False,
    )
    actor: orm.Mapped[str] = orm.mapped_column(sa.String(240), nullable=False)
    status: orm.Mapped[GenerationRunStatus] = orm.mapped_column(
        GENERATION_RUN_STATUS,
        nullable=False,
        index=True,
    )
    current_node: orm.Mapped[str | None] = orm.mapped_column(
        sa.String(160),
        nullable=True,
    )
    budget_snapshot: orm.Mapped[JsonMapping] = orm.mapped_column(
        postgresql.JSONB,
        nullable=False,
    )
    configuration: orm.Mapped[JsonMapping] = orm.mapped_column(
        postgresql.JSONB,
        nullable=False,
    )
    quality_mode: orm.Mapped[QualityMode] = orm.mapped_column(
        QUALITY_MODE,
        nullable=False,
    )
    qa_status: orm.Mapped[QaStatus | None] = orm.mapped_column(
        QA_STATUS,
        nullable=True,
    )
    skip_qa_rationale: orm.Mapped[str | None] = orm.mapped_column(
        sa.Text,
        nullable=True,
    )
    idempotency_key: orm.Mapped[str | None] = orm.mapped_column(
        sa.String(512),
        nullable=True,
        unique=True,
    )
    error_message: orm.Mapped[str | None] = orm.mapped_column(sa.Text, nullable=True)
    error_category: orm.Mapped[str | None] = orm.mapped_column(
        sa.String(120),
        nullable=True,
    )
    lease_expires_at: orm.Mapped[dt.datetime | None] = orm.mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
    )
    started_at: orm.Mapped[dt.datetime | None] = orm.mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    ended_at: orm.Mapped[dt.datetime | None] = orm.mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
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


class GenerationEventRecord(Base):
    """SQLAlchemy model for append-only generation-run events."""

    __tablename__ = "generation_events"
    __table_args__ = (
        sa.UniqueConstraint(
            "generation_run_id",
            "seq",
            name="uq_generation_events_run_seq",
        ),
    )

    id: orm.Mapped[uuid.UUID] = orm.mapped_column(
        postgresql.UUID(as_uuid=True),
        primary_key=True,
    )
    generation_run_id: orm.Mapped[uuid.UUID] = orm.mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("generation_runs.id"),
        nullable=False,
        index=True,
    )
    seq: orm.Mapped[int] = orm.mapped_column(sa.Integer, nullable=False)
    kind: orm.Mapped[str] = orm.mapped_column(sa.String(160), nullable=False)
    payload: orm.Mapped[JsonMapping] = orm.mapped_column(
        postgresql.JSONB,
        nullable=False,
    )
    occurred_at: orm.Mapped[dt.datetime] = orm.mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
    )
    created_at: orm.Mapped[dt.datetime] = orm.mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )
