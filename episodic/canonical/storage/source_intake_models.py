"""SQLAlchemy models for source-intake upload persistence."""

import datetime as dt  # noqa: TC003  # SQLAlchemy evaluates annotations at runtime.
import uuid  # noqa: TC003  # SQLAlchemy evaluates annotations at runtime.

import sqlalchemy as sa
from sqlalchemy import orm
from sqlalchemy.dialects import postgresql

from episodic.canonical.idempotency import (  # noqa: TC001
    IdempotencyState,
)
from episodic.canonical.ingestion_sources import (  # noqa: TC001
    AttachmentKind,
)
from episodic.canonical.uploads import UploadState  # noqa: TC001

from .models_base import (
    ATTACHMENT_KIND,
    IDEMPOTENCY_STATE,
    UPLOAD_STATE,
    Base,
)


class UploadRecord(Base):
    """Persist metadata for bytes stored behind the object-store port."""

    __tablename__ = "uploads"

    id: orm.Mapped[uuid.UUID] = orm.mapped_column(
        postgresql.UUID(as_uuid=True),
        primary_key=True,
    )
    owner_principal_id: orm.Mapped[str | None] = orm.mapped_column(
        sa.String(200),
        nullable=True,
    )
    content_type: orm.Mapped[str] = orm.mapped_column(sa.String(255), nullable=False)
    declared_size: orm.Mapped[int] = orm.mapped_column(sa.BigInteger, nullable=False)
    actual_size: orm.Mapped[int | None] = orm.mapped_column(
        sa.BigInteger,
        nullable=True,
    )
    declared_sha256: orm.Mapped[str | None] = orm.mapped_column(
        sa.String(64),
        nullable=True,
    )
    content_hash: orm.Mapped[str | None] = orm.mapped_column(
        sa.String(80),
        nullable=True,
    )
    storage_key: orm.Mapped[str] = orm.mapped_column(
        sa.Text,
        nullable=False,
        unique=True,
    )
    state: orm.Mapped[UploadState] = orm.mapped_column(
        UPLOAD_STATE,
        nullable=False,
    )
    metadata_payload: orm.Mapped[dict[str, object]] = orm.mapped_column(
        "metadata",
        postgresql.JSONB,
        default=dict,
        nullable=False,
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

    __table_args__ = (
        sa.CheckConstraint("declared_size >= 0", name="ck_uploads_declared_size"),
        sa.CheckConstraint(
            "actual_size IS NULL OR actual_size >= 0", name="ck_uploads_actual_size"
        ),
        sa.Index("ix_uploads_state_created_at", "state", "created_at"),
    )


class IngestionJobSourceRecord(Base):
    """Persist a pre-generation source attached to an ingestion job."""

    __tablename__ = "ingestion_job_sources"

    id: orm.Mapped[uuid.UUID] = orm.mapped_column(
        postgresql.UUID(as_uuid=True),
        primary_key=True,
    )
    ingestion_job_id: orm.Mapped[uuid.UUID] = orm.mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("ingestion_jobs.id"),
        nullable=False,
        index=True,
    )
    attachment_kind: orm.Mapped[AttachmentKind] = orm.mapped_column(
        ATTACHMENT_KIND,
        nullable=False,
    )
    upload_id: orm.Mapped[uuid.UUID | None] = orm.mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("uploads.id"),
        nullable=True,
        index=True,
    )
    source_uri: orm.Mapped[str | None] = orm.mapped_column(sa.Text, nullable=True)
    source_type: orm.Mapped[str] = orm.mapped_column(sa.String(120), nullable=False)
    weight: orm.Mapped[float] = orm.mapped_column(sa.Float, nullable=False)
    metadata_payload: orm.Mapped[dict[str, object]] = orm.mapped_column(
        "metadata",
        postgresql.JSONB,
        default=dict,
        nullable=False,
    )
    created_at: orm.Mapped[dt.datetime] = orm.mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )

    __table_args__ = (
        sa.CheckConstraint(
            "weight >= 0 AND weight <= 1",
            name="ck_ingestion_job_sources_weight",
        ),
        sa.CheckConstraint(
            "(upload_id IS NOT NULL AND source_uri IS NULL) OR "
            "(upload_id IS NULL AND source_uri IS NOT NULL)",
            name="ck_ingestion_job_sources_exactly_one_source",
        ),
    )


class IdempotencyRecordModel(Base):
    """Persist idempotent side-effect fingerprints and opaque outcomes."""

    __tablename__ = "idempotency_records"

    id: orm.Mapped[uuid.UUID] = orm.mapped_column(
        postgresql.UUID(as_uuid=True),
        primary_key=True,
    )
    principal_id: orm.Mapped[str] = orm.mapped_column(
        sa.String(200),
        nullable=False,
    )
    operation: orm.Mapped[str] = orm.mapped_column(sa.String(120), nullable=False)
    idempotency_key: orm.Mapped[str] = orm.mapped_column(
        sa.String(512),
        nullable=False,
    )
    body_hash: orm.Mapped[str] = orm.mapped_column(sa.String(128), nullable=False)
    state: orm.Mapped[IdempotencyState] = orm.mapped_column(
        IDEMPOTENCY_STATE,
        nullable=False,
    )
    serialised_outcome: orm.Mapped[bytes | None] = orm.mapped_column(
        postgresql.BYTEA,
        nullable=True,
    )
    expires_at: orm.Mapped[dt.datetime] = orm.mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        index=True,
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

    __table_args__ = (
        sa.UniqueConstraint(
            "principal_id",
            "operation",
            "idempotency_key",
            name="uq_idempotency_records_principal_operation_key",
        ),
        sa.CheckConstraint(
            "state != 'completed' OR serialised_outcome IS NOT NULL",
            name="ck_idempotency_records_completed_outcome",
        ),
    )
