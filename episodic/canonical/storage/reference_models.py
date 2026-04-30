"""Reference-document SQLAlchemy ORM models for canonical persistence."""

import datetime as dt  # noqa: TC003  # SQLAlchemy evaluates annotations at runtime.
import uuid  # noqa: TC003  # SQLAlchemy evaluates annotations at runtime.

import sqlalchemy as sa
from sqlalchemy import orm
from sqlalchemy.dialects import postgresql

from episodic.canonical.constraints import (
    CK_REFERENCE_BINDINGS_EFFECTIVE_EPISODE,
    CK_REFERENCE_BINDINGS_TARGET,
    UQ_REF_DOC_BINDINGS_JOB_REV,
    UQ_REF_DOC_BINDINGS_SERIES_REV_EFFECTIVE,
    UQ_REF_DOC_BINDINGS_SERIES_REV_NO_EFFECTIVE,
    UQ_REF_DOC_BINDINGS_TEMPLATE_REV,
)
from episodic.canonical.domain import (
    ReferenceBindingTargetKind,
    ReferenceDocumentKind,
    ReferenceDocumentLifecycleState,
)
from episodic.canonical.storage.reference_document_schema import (
    REFERENCE_BINDINGS_EFFECTIVE_EPISODE_CHECK_SQL,
    REFERENCE_BINDINGS_TARGET_CHECK_SQL,
)

from .models import (
    REFERENCE_BINDING_TARGET_KIND,
    REFERENCE_DOCUMENT_KIND,
    REFERENCE_DOCUMENT_LIFECYCLE_STATE,
    Base,
)


class ReferenceDocumentRecord(Base):
    """SQLAlchemy model for reusable reference documents.

    Attributes
    ----------
    id : uuid.UUID
        Primary key for the reference document.
    owner_series_profile_id : uuid.UUID
        Foreign key to the owning series profile.
    kind : ReferenceDocumentKind
        Document kind enum describing reusable profile/brief intent.
    lifecycle_state : ReferenceDocumentLifecycleState
        Lifecycle state enum for activation/archive workflows.
    metadata_payload : dict[str, object]
        JSON metadata payload stored under the ``metadata`` column.
    lock_version : int
        Optimistic-lock token incremented on each successful update.
    created_at : datetime.datetime
        Timestamp when the record was created.
    updated_at : datetime.datetime
        Timestamp when the record was last updated.
    """

    __tablename__ = "reference_documents"

    id: orm.Mapped[uuid.UUID] = orm.mapped_column(
        postgresql.UUID(as_uuid=True),
        primary_key=True,
    )
    owner_series_profile_id: orm.Mapped[uuid.UUID] = orm.mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("series_profiles.id"),
        nullable=False,
        index=True,
    )
    kind: orm.Mapped[ReferenceDocumentKind] = orm.mapped_column(
        REFERENCE_DOCUMENT_KIND,
        nullable=False,
    )
    lifecycle_state: orm.Mapped[ReferenceDocumentLifecycleState] = orm.mapped_column(
        REFERENCE_DOCUMENT_LIFECYCLE_STATE,
        nullable=False,
    )
    metadata_payload: orm.Mapped[dict[str, object]] = orm.mapped_column(
        "metadata",
        postgresql.JSONB,
        default=dict,
        nullable=False,
    )
    lock_version: orm.Mapped[int] = orm.mapped_column(
        sa.Integer,
        nullable=False,
        server_default=sa.text("1"),
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
        sa.CheckConstraint(
            "lock_version >= 1",
            name="ck_reference_documents_lock_version_positive",
        ),
    )


class ReferenceDocumentRevisionRecord(Base):
    """SQLAlchemy model for immutable reusable reference revisions.

    Attributes
    ----------
    id : uuid.UUID
        Primary key for the immutable reference revision.
    reference_document_id : uuid.UUID
        Foreign key to the parent reference document.
    content_payload : dict[str, object]
        JSON revision content stored under the ``content`` column.
    content_hash : str
        Deterministic hash for revision deduplication.
    author : str | None
        Optional author identifier for audit trails.
    change_note : str | None
        Optional human-readable note describing revision intent.
    created_at : datetime.datetime
        Timestamp when the revision was created.
    """

    __tablename__ = "reference_document_revisions"

    id: orm.Mapped[uuid.UUID] = orm.mapped_column(
        postgresql.UUID(as_uuid=True),
        primary_key=True,
    )
    reference_document_id: orm.Mapped[uuid.UUID] = orm.mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("reference_documents.id"),
        nullable=False,
        index=True,
    )
    content_payload: orm.Mapped[dict[str, object]] = orm.mapped_column(
        "content",
        postgresql.JSONB,
        nullable=False,
    )
    content_hash: orm.Mapped[str] = orm.mapped_column(sa.String(128), nullable=False)
    author: orm.Mapped[str | None] = orm.mapped_column(sa.String(200), nullable=True)
    change_note: orm.Mapped[str | None] = orm.mapped_column(sa.Text, nullable=True)
    created_at: orm.Mapped[dt.datetime] = orm.mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )

    __table_args__ = (
        sa.UniqueConstraint(
            "reference_document_id",
            "content_hash",
            name="uq_reference_document_revisions_document_hash",
        ),
    )


class ReferenceBindingRecord(Base):
    """SQLAlchemy model for reusable reference bindings.

    Attributes
    ----------
    id : uuid.UUID
        Primary key for the reference binding.
    reference_document_revision_id : uuid.UUID
        Foreign key to the bound immutable reference revision.
    target_kind : ReferenceBindingTargetKind
        Target context kind enum (series profile, template, or ingestion job).
    series_profile_id : uuid.UUID | None
        Series profile target identifier when ``target_kind`` is series profile.
    episode_template_id : uuid.UUID | None
        Episode template target identifier when ``target_kind`` is template.
    ingestion_job_id : uuid.UUID | None
        Ingestion job target identifier when ``target_kind`` is ingestion job.
    effective_from_episode_id : uuid.UUID | None
        Optional episode boundary for series-profile target applicability.
    created_at : datetime.datetime
        Timestamp when the binding was created.
    """

    __tablename__ = "reference_document_bindings"

    id: orm.Mapped[uuid.UUID] = orm.mapped_column(
        postgresql.UUID(as_uuid=True),
        primary_key=True,
    )
    reference_document_revision_id: orm.Mapped[uuid.UUID] = orm.mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("reference_document_revisions.id"),
        nullable=False,
        index=True,
    )
    target_kind: orm.Mapped[ReferenceBindingTargetKind] = orm.mapped_column(
        REFERENCE_BINDING_TARGET_KIND,
        nullable=False,
    )
    series_profile_id: orm.Mapped[uuid.UUID | None] = orm.mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("series_profiles.id"),
        nullable=True,
        index=True,
    )
    episode_template_id: orm.Mapped[uuid.UUID | None] = orm.mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("episode_templates.id"),
        nullable=True,
        index=True,
    )
    ingestion_job_id: orm.Mapped[uuid.UUID | None] = orm.mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("ingestion_jobs.id"),
        nullable=True,
        index=True,
    )
    effective_from_episode_id: orm.Mapped[uuid.UUID | None] = orm.mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("episodes.id"),
        nullable=True,
    )
    created_at: orm.Mapped[dt.datetime] = orm.mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )

    __table_args__ = (
        sa.CheckConstraint(
            REFERENCE_BINDINGS_TARGET_CHECK_SQL,
            name=CK_REFERENCE_BINDINGS_TARGET,
        ),
        sa.CheckConstraint(
            REFERENCE_BINDINGS_EFFECTIVE_EPISODE_CHECK_SQL,
            name=CK_REFERENCE_BINDINGS_EFFECTIVE_EPISODE,
        ),
        sa.Index(
            UQ_REF_DOC_BINDINGS_SERIES_REV_EFFECTIVE,
            reference_document_revision_id,
            series_profile_id,
            effective_from_episode_id,
            unique=True,
            postgresql_where=sa.and_(
                target_kind == ReferenceBindingTargetKind.SERIES_PROFILE,
                effective_from_episode_id.is_not(None),
            ),
        ),
        sa.Index(
            UQ_REF_DOC_BINDINGS_SERIES_REV_NO_EFFECTIVE,
            reference_document_revision_id,
            series_profile_id,
            unique=True,
            postgresql_where=sa.and_(
                target_kind == ReferenceBindingTargetKind.SERIES_PROFILE,
                effective_from_episode_id.is_(None),
            ),
        ),
        sa.Index(
            UQ_REF_DOC_BINDINGS_TEMPLATE_REV,
            reference_document_revision_id,
            episode_template_id,
            unique=True,
            postgresql_where=target_kind == ReferenceBindingTargetKind.EPISODE_TEMPLATE,
        ),
        sa.Index(
            UQ_REF_DOC_BINDINGS_JOB_REV,
            reference_document_revision_id,
            ingestion_job_id,
            unique=True,
            postgresql_where=target_kind == ReferenceBindingTargetKind.INGESTION_JOB,
        ),
    )
