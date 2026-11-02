"""SQLAlchemy model for user-facing generation-run review checkpoints."""

import datetime as dt  # ruff: ignore[typing-only-standard-library-import]  # SQLAlchemy evaluates annotations at runtime.
import uuid  # ruff: ignore[typing-only-standard-library-import]  # SQLAlchemy evaluates annotations at runtime.

import sqlalchemy as sa
from sqlalchemy import orm
from sqlalchemy.dialects import postgresql

from episodic.canonical.domain import (  # ruff: ignore[typing-only-first-party-import]  # SQLAlchemy evaluates annotations at runtime.
    CheckpointAction,
    CheckpointStatus,
    JsonMapping,
)

from .models_base import (
    REVIEW_CHECKPOINT_ACTION,
    REVIEW_CHECKPOINT_STATUS,
    Base,
)


class ReviewCheckpointRecord(Base):
    """SQLAlchemy model for a durable reviewer checkpoint.

    The column is named ``resolved_at`` rather than the domain field's
    ``responded_at``: a checkpoint also leaves ``created`` by timing out or
    being cancelled, and two of the three transitions have no responder. The
    mapper bridges the two names.
    """

    __tablename__ = "review_checkpoints"

    id: orm.Mapped[uuid.UUID] = orm.mapped_column(
        postgresql.UUID(as_uuid=True),
        primary_key=True,
    )
    # RESTRICT, not CASCADE: ADR-018's audit-trail policy keeps reviewer
    # decisions out of reach of a parent-row delete.
    generation_run_id: orm.Mapped[uuid.UUID] = orm.mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("generation_runs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    node: orm.Mapped[str] = orm.mapped_column(sa.String(160), nullable=False)
    prompt: orm.Mapped[str] = orm.mapped_column(sa.Text, nullable=False)
    options: orm.Mapped[list[str]] = orm.mapped_column(
        postgresql.JSONB,
        nullable=False,
    )
    status: orm.Mapped[CheckpointStatus] = orm.mapped_column(
        REVIEW_CHECKPOINT_STATUS,
        nullable=False,
    )
    response_action: orm.Mapped[CheckpointAction | None] = orm.mapped_column(
        REVIEW_CHECKPOINT_ACTION,
        nullable=True,
    )
    # Non-optional with a server default: the domain type is a non-optional
    # mapping, so a nullable column would admit two encodings of one value.
    response_payload: orm.Mapped[JsonMapping] = orm.mapped_column(
        postgresql.JSONB,
        nullable=False,
        server_default=sa.text("'{}'::jsonb"),
    )
    resolved_at: orm.Mapped[dt.datetime | None] = orm.mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
    )
    responded_by: orm.Mapped[str | None] = orm.mapped_column(
        sa.String(240),
        nullable=True,
    )
    created_at: orm.Mapped[dt.datetime] = orm.mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )
    # Storage-only, for operational triage. Its `onupdate` is a client-side
    # default, so a raw-SQL update leaves it stale and `compare_metadata` will
    # not notice; set it explicitly in any bulk statement.
    updated_at: orm.Mapped[dt.datetime] = orm.mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )

    __table_args__ = (
        sa.CheckConstraint(
            "jsonb_typeof(options) = 'array' AND jsonb_array_length(options) > 0",
            name="ck_review_checkpoints_options_array",
        ),
        sa.CheckConstraint(
            "status <> 'responded' OR ("
            " response_action IS NOT NULL"
            " AND responded_by IS NOT NULL"
            " AND resolved_at IS NOT NULL)",
            name="ck_review_checkpoints_responded_fields",
        ),
        sa.Index(
            "ix_review_checkpoints_run_status",
            "generation_run_id",
            "status",
        ),
        # No standalone index on `status`: it has four values, terminal rows
        # accumulate monotonically, and PostgreSQL would seq-scan past it for
        # anything but a tiny table. This partial index stays small forever.
        sa.Index(
            "ix_review_checkpoints_open",
            "generation_run_id",
            postgresql_where=sa.text("status = 'created'"),
        ),
    )
