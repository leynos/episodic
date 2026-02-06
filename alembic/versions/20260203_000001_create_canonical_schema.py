"""Create the canonical content schema for ingestion and approval workflows.

This migration defines the canonical tables, enums, and indexes used to store
series profiles, TEI headers, episodes, ingestion jobs, source documents, and
approval events. It is the foundational schema for canonical ingestion and
approval auditing.

Examples
--------
Apply the migration with Alembic:

>>> alembic upgrade head
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260203_000001"
down_revision = None
branch_labels = None
depends_on = None


def _episode_status_enum() -> postgresql.ENUM:
    return postgresql.ENUM(
        "draft",
        "in_progress",
        "quality_review",
        "editorial_review",
        "on_hold",
        "rejected",
        "audio_generation",
        "post_processing",
        "ready_to_publish",
        "scheduled",
        "published",
        "updated",
        "failed",
        "archived",
        name="episode_status",
        create_type=False,
    )


def _approval_state_enum() -> postgresql.ENUM:
    return postgresql.ENUM(
        "draft",
        "submitted",
        "approved",
        "rejected",
        name="approval_state",
        create_type=False,
    )


def _ingestion_status_enum() -> postgresql.ENUM:
    return postgresql.ENUM(
        "pending",
        "running",
        "completed",
        "failed",
        name="ingestion_status",
        create_type=False,
    )


def _timestamp_columns() -> list[sa.Column]:
    """Create shared created_at and updated_at columns."""
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    ]


def _create_series_profiles_table() -> None:
    """Create the series_profiles table."""
    op.create_table(
        "series_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("slug", sa.String(160), nullable=False, unique=True),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("configuration", postgresql.JSONB(), nullable=False),
        *_timestamp_columns(),
    )


def _create_tei_headers_table() -> None:
    """Create the tei_headers table."""
    op.create_table(
        "tei_headers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("raw_xml", sa.Text(), nullable=False),
        *_timestamp_columns(),
    )


def _create_episodes_table(
    episode_status: postgresql.ENUM,
    approval_state: postgresql.ENUM,
) -> None:
    """Create the episodes table."""
    op.create_table(
        "episodes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "series_profile_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("series_profiles.id"),
            nullable=False,
        ),
        sa.Column(
            "tei_header_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tei_headers.id"),
            nullable=False,
        ),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("tei_xml", sa.Text(), nullable=False),
        sa.Column("status", episode_status, nullable=False),
        sa.Column("approval_state", approval_state, nullable=False),
        *_timestamp_columns(),
    )
    op.create_index(
        "ix_episodes_series_profile_id",
        "episodes",
        ["series_profile_id"],
    )


def _create_ingestion_jobs_table(ingestion_status: postgresql.ENUM) -> None:
    """Create the ingestion_jobs table."""
    op.create_table(
        "ingestion_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "series_profile_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("series_profiles.id"),
            nullable=False,
        ),
        sa.Column(
            "target_episode_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("episodes.id"),
            nullable=True,
        ),
        sa.Column("status", ingestion_status, nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        *_timestamp_columns(),
    )
    op.create_index(
        "ix_ingestion_jobs_series_profile_id",
        "ingestion_jobs",
        ["series_profile_id"],
    )


def _create_source_documents_table() -> None:
    """Create the source_documents table."""
    op.create_table(
        "source_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "ingestion_job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ingestion_jobs.id"),
            nullable=False,
        ),
        sa.Column(
            "canonical_episode_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("episodes.id"),
            nullable=True,
        ),
        sa.Column("source_type", sa.String(120), nullable=False),
        sa.Column("source_uri", sa.Text(), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False),
        sa.Column("content_hash", sa.String(128), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "weight >= 0 AND weight <= 1",
            name="ck_source_documents_weight",
        ),
    )
    op.create_index(
        "ix_source_documents_ingestion_job_id",
        "source_documents",
        ["ingestion_job_id"],
    )


def _create_approval_events_table(approval_state: postgresql.ENUM) -> None:
    """Create the approval_events table."""
    op.create_table(
        "approval_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "episode_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("episodes.id"),
            nullable=False,
        ),
        sa.Column("actor", sa.String(200), nullable=True),
        sa.Column("from_state", approval_state, nullable=True),
        sa.Column("to_state", approval_state, nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_approval_events_episode_id",
        "approval_events",
        ["episode_id"],
    )


def upgrade() -> None:
    """Apply schema changes."""
    episode_status = _episode_status_enum()
    approval_state = _approval_state_enum()
    ingestion_status = _ingestion_status_enum()

    bind = op.get_bind()
    episode_status.create(bind, checkfirst=True)
    approval_state.create(bind, checkfirst=True)
    ingestion_status.create(bind, checkfirst=True)

    _create_series_profiles_table()
    _create_tei_headers_table()
    _create_episodes_table(episode_status, approval_state)
    _create_ingestion_jobs_table(ingestion_status)
    _create_source_documents_table()
    _create_approval_events_table(approval_state)


def downgrade() -> None:
    """Revert schema changes."""
    op.drop_index("ix_approval_events_episode_id", table_name="approval_events")
    op.drop_table("approval_events")
    op.drop_index("ix_source_documents_ingestion_job_id", table_name="source_documents")
    op.drop_table("source_documents")
    op.drop_index(
        "ix_ingestion_jobs_series_profile_id",
        table_name="ingestion_jobs",
    )
    op.drop_table("ingestion_jobs")
    op.drop_index("ix_episodes_series_profile_id", table_name="episodes")
    op.drop_table("episodes")
    op.drop_table("tei_headers")
    op.drop_table("series_profiles")

    bind = op.get_bind()
    _ingestion_status_enum().drop(bind, checkfirst=True)
    _approval_state_enum().drop(bind, checkfirst=True)
    _episode_status_enum().drop(bind, checkfirst=True)
