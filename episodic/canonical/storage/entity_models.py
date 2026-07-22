"""Content SQLAlchemy ORM models for canonical content."""

import datetime as dt  # noqa: TC003  # SQLAlchemy evaluates annotations at runtime.
import uuid  # noqa: TC003  # SQLAlchemy evaluates annotations at runtime.

import sqlalchemy as sa
from sqlalchemy import orm
from sqlalchemy.dialects import postgresql

from episodic.canonical.domain import (  # SQLAlchemy evaluates annotations at runtime.
    ApprovalState,
    EpisodeStatus,
    IngestionStatus,
    IntakeState,
)
from episodic.canonical.generation_quality import QaStatus  # noqa: TC001

from .models_base import (
    APPROVAL_STATE,
    EPISODE_STATUS,
    INGESTION_STATUS,
    INTAKE_STATE,
    QA_STATUS,
    Base,
)


class TeiHeaderRecord(Base):
    """SQLAlchemy model for parsed TEI headers.

    Attributes
    ----------
    id : uuid.UUID
        Primary key for the TEI header.
    title : str
        Derived title from the TEI header.
    payload : dict[str, object]
        Parsed TEI header payload stored as JSONB.
    raw_xml : str
        Raw TEI XML payload for auditing or reprocessing.
    raw_xml_zstd : bytes | None
        Zstandard-compressed TEI XML payload for large records.
    created_at : datetime.datetime
        Timestamp when the record was created.
    updated_at : datetime.datetime
        Timestamp when the record was last updated.
    """

    __tablename__ = "tei_headers"

    id: orm.Mapped[uuid.UUID] = orm.mapped_column(
        postgresql.UUID(as_uuid=True),
        primary_key=True,
    )
    title: orm.Mapped[str] = orm.mapped_column(sa.String(240), nullable=False)
    payload: orm.Mapped[dict[str, object]] = orm.mapped_column(
        postgresql.JSONB,
        nullable=False,
    )
    raw_xml: orm.Mapped[str] = orm.mapped_column(sa.Text, nullable=False)
    raw_xml_zstd: orm.Mapped[bytes | None] = orm.mapped_column(
        postgresql.BYTEA,
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


class EpisodeRecord(Base):
    """SQLAlchemy model for canonical episodes.

    Attributes
    ----------
    id : uuid.UUID
        Primary key for the episode.
    series_profile_id : uuid.UUID
        Foreign key to the series profile.
    tei_header_id : uuid.UUID
        Foreign key to the TEI header.
    title : str
        Episode title.
    tei_xml : str
        Raw TEI XML associated with the episode.
    tei_xml_zstd : bytes | None
        Zstandard-compressed TEI XML associated with the episode.
    tei_revision : int
        Monotonic TEI revision number for the episode.
    tei_content_hash : str | None
        Content hash for the current TEI payload, when available.
    qa_status : QaStatus | None
        Quality-assurance status for the current episode content.
    last_generation_run_id : uuid.UUID | None
        Most recent generation run associated with the episode.
    status : EpisodeStatus
        Episode status enum.
    approval_state : ApprovalState
        Approval state enum for the episode.
    created_at : datetime.datetime
        Timestamp when the record was created.
    updated_at : datetime.datetime
        Timestamp when the record was last updated.
    """

    __tablename__ = "episodes"

    id: orm.Mapped[uuid.UUID] = orm.mapped_column(
        postgresql.UUID(as_uuid=True),
        primary_key=True,
    )
    series_profile_id: orm.Mapped[uuid.UUID] = orm.mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("series_profiles.id"),
        nullable=False,
        index=True,
    )
    tei_header_id: orm.Mapped[uuid.UUID] = orm.mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("tei_headers.id"),
        nullable=False,
    )
    title: orm.Mapped[str] = orm.mapped_column(sa.String(240), nullable=False)
    tei_xml: orm.Mapped[str] = orm.mapped_column(sa.Text, nullable=False)
    tei_xml_zstd: orm.Mapped[bytes | None] = orm.mapped_column(
        postgresql.BYTEA,
        nullable=True,
    )
    tei_revision: orm.Mapped[int] = orm.mapped_column(
        sa.Integer,
        nullable=False,
        server_default="1",
    )
    tei_content_hash: orm.Mapped[str | None] = orm.mapped_column(
        sa.String(128),
        nullable=True,
    )
    qa_status: orm.Mapped[QaStatus | None] = orm.mapped_column(
        QA_STATUS,
        nullable=True,
    )
    last_generation_run_id: orm.Mapped[uuid.UUID | None] = orm.mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("generation_runs.id"),
        nullable=True,
    )
    status: orm.Mapped[EpisodeStatus] = orm.mapped_column(
        EPISODE_STATUS,
        nullable=False,
    )
    approval_state: orm.Mapped[ApprovalState] = orm.mapped_column(
        APPROVAL_STATE,
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


class IngestionJobRecord(Base):
    """SQLAlchemy model for ingestion jobs.

    Attributes
    ----------
    id : uuid.UUID
        Primary key for the ingestion job.
    series_profile_id : uuid.UUID
        Foreign key to the series profile.
    target_episode_id : uuid.UUID | None
        Foreign key to the target episode, when available.
    status : IngestionStatus
        Status enum for the job lifecycle.
    requested_at : datetime.datetime
        Timestamp when the job was requested.
    started_at : datetime.datetime | None
        Timestamp when the job started.
    completed_at : datetime.datetime | None
        Timestamp when the job completed.
    error_message : str | None
        Error details when the job fails.
    created_at : datetime.datetime
        Timestamp when the record was created.
    updated_at : datetime.datetime
        Timestamp when the record was last updated.
    """

    __tablename__ = "ingestion_jobs"

    id: orm.Mapped[uuid.UUID] = orm.mapped_column(
        postgresql.UUID(as_uuid=True),
        primary_key=True,
    )
    series_profile_id: orm.Mapped[uuid.UUID] = orm.mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("series_profiles.id"),
        nullable=False,
        index=True,
    )
    target_episode_id: orm.Mapped[uuid.UUID | None] = orm.mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("episodes.id"),
        nullable=True,
    )
    status: orm.Mapped[IngestionStatus] = orm.mapped_column(
        INGESTION_STATUS,
        nullable=False,
    )
    requested_at: orm.Mapped[dt.datetime] = orm.mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
    )
    started_at: orm.Mapped[dt.datetime | None] = orm.mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
    )
    completed_at: orm.Mapped[dt.datetime | None] = orm.mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
    )
    error_message: orm.Mapped[str | None] = orm.mapped_column(sa.Text, nullable=True)
    intake_state: orm.Mapped[IntakeState] = orm.mapped_column(
        INTAKE_STATE,
        nullable=False,
        server_default=IntakeState.AWAITING_SOURCES.value,
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
        sa.Index(
            "ix_ingestion_jobs_series_profile_intake_state_created_at",
            "series_profile_id",
            "intake_state",
            sa.desc("created_at"),
        ),
    )


class SourceDocumentRecord(Base):
    """SQLAlchemy model for source documents.

    Attributes
    ----------
    id : uuid.UUID
        Primary key for the source document.
    ingestion_job_id : uuid.UUID
        Foreign key to the ingestion job.
    canonical_episode_id : uuid.UUID | None
        Foreign key to the canonical episode, set on creation for immutable records.
    reference_document_revision_id : uuid.UUID | None
        Foreign key to the reference document revision, populated when snapshotting
        resolved bindings as provenance.
    source_type : str
        Source type label (for example, transcript or web).
    source_uri : str
        URI pointing to the source content.
    weight : float
        Normalized weight assigned to the source.
    content_hash : str
        Hash of the source content for deduplication.
    metadata_payload : dict[str, object]
        JSON metadata payload stored under the ``metadata`` column.
    created_at : datetime.datetime
        Timestamp when the record was created.
    """

    __tablename__ = "source_documents"

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
    canonical_episode_id: orm.Mapped[uuid.UUID | None] = orm.mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("episodes.id"),
        nullable=True,
    )
    reference_document_revision_id: orm.Mapped[uuid.UUID | None] = orm.mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("reference_document_revisions.id"),
        nullable=True,
        index=True,
    )
    source_type: orm.Mapped[str] = orm.mapped_column(sa.String(120), nullable=False)
    source_uri: orm.Mapped[str] = orm.mapped_column(sa.Text, nullable=False)
    weight: orm.Mapped[float] = orm.mapped_column(sa.Float, nullable=False)
    content_hash: orm.Mapped[str] = orm.mapped_column(sa.String(128), nullable=False)
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
            name="ck_source_documents_weight",
        ),
    )


class ApprovalEventRecord(Base):
    """SQLAlchemy model for approval events.

    Attributes
    ----------
    id : uuid.UUID
        Primary key for the approval event.
    episode_id : uuid.UUID
        Foreign key to the episode being approved.
    actor : str | None
        Optional identifier for the approving actor.
    from_state : ApprovalState | None
        Previous approval state, when available.
    to_state : ApprovalState
        New approval state after the transition.
    note : str | None
        Optional free-form note.
    payload : dict[str, object]
        Supplemental metadata for the approval event.
    created_at : datetime.datetime
        Timestamp when the record was created.
    """

    __tablename__ = "approval_events"

    id: orm.Mapped[uuid.UUID] = orm.mapped_column(
        postgresql.UUID(as_uuid=True),
        primary_key=True,
    )
    episode_id: orm.Mapped[uuid.UUID] = orm.mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("episodes.id"),
        nullable=False,
        index=True,
    )
    actor: orm.Mapped[str | None] = orm.mapped_column(sa.String(200), nullable=True)
    from_state: orm.Mapped[ApprovalState | None] = orm.mapped_column(
        APPROVAL_STATE,
        nullable=True,
    )
    to_state: orm.Mapped[ApprovalState] = orm.mapped_column(
        APPROVAL_STATE,
        nullable=False,
    )
    note: orm.Mapped[str | None] = orm.mapped_column(sa.Text, nullable=True)
    payload: orm.Mapped[dict[str, object]] = orm.mapped_column(
        postgresql.JSONB,
        default=dict,
        nullable=False,
    )
    created_at: orm.Mapped[dt.datetime] = orm.mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )
