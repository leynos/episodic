"""Add source-intake upload and idempotency tables."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260610_000009"
down_revision = "20260508_000008"
branch_labels = None
depends_on = None


def _enum(name: str, *values: str) -> postgresql.ENUM:
    """Return an existing-or-creatable PostgreSQL enum."""
    return postgresql.ENUM(*values, name=name, create_type=False)


def upgrade() -> None:
    """Create source-intake tables and intake-state columns."""
    _enum(
        "intake_state", "awaiting_sources", "ready_for_generation", "cancelled"
    ).create(
        op.get_bind(),
        checkfirst=True,
    )
    _enum("upload_state", "pending", "ready", "failed", "expired").create(
        op.get_bind(),
        checkfirst=True,
    )
    _enum("attachment_kind", "upload", "source_uri").create(
        op.get_bind(),
        checkfirst=True,
    )
    _enum("idempotency_state", "in_flight", "completed").create(
        op.get_bind(),
        checkfirst=True,
    )

    op.add_column(
        "ingestion_jobs",
        sa.Column(
            "intake_state",
            _enum(
                "intake_state", "awaiting_sources", "ready_for_generation", "cancelled"
            ),
            server_default="awaiting_sources",
            nullable=False,
        ),
    )
    op.create_index(
        "ix_ingestion_jobs_series_profile_intake_state_created_at",
        "ingestion_jobs",
        ["series_profile_id", "intake_state", sa.text("created_at DESC")],
    )
    op.create_table(
        "uploads",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("owner_principal_id", sa.String(length=200), nullable=True),
        sa.Column("content_type", sa.String(length=255), nullable=False),
        sa.Column("declared_size", sa.BigInteger(), nullable=False),
        sa.Column("actual_size", sa.BigInteger(), nullable=True),
        sa.Column("declared_sha256", sa.String(length=64), nullable=True),
        sa.Column("content_hash", sa.String(length=80), nullable=True),
        sa.Column("storage_key", sa.Text(), nullable=False, unique=True),
        sa.Column(
            "state",
            _enum("upload_state", "pending", "ready", "failed", "expired"),
            nullable=False,
        ),
        sa.Column("metadata", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("declared_size >= 0", name="ck_uploads_declared_size"),
        sa.CheckConstraint(
            "actual_size IS NULL OR actual_size >= 0",
            name="ck_uploads_actual_size",
        ),
    )
    op.create_index(
        "ix_uploads_state_created_at",
        "uploads",
        ["state", "created_at"],
    )
    op.create_table(
        "ingestion_job_sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "ingestion_job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ingestion_jobs.id"),
            nullable=False,
        ),
        sa.Column(
            "attachment_kind",
            _enum("attachment_kind", "upload", "source_uri"),
            nullable=False,
        ),
        sa.Column(
            "upload_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("uploads.id"),
            nullable=True,
        ),
        sa.Column("source_uri", sa.Text(), nullable=True),
        sa.Column("source_type", sa.String(length=120), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
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
    op.create_index(
        "ix_ingestion_job_sources_ingestion_job_id",
        "ingestion_job_sources",
        ["ingestion_job_id"],
    )
    op.create_index(
        "ix_ingestion_job_sources_upload_id",
        "ingestion_job_sources",
        ["upload_id"],
    )
    op.create_table(
        "idempotency_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("principal_id", sa.String(length=200), nullable=False),
        sa.Column("operation", sa.String(length=120), nullable=False),
        sa.Column("idempotency_key", sa.String(length=512), nullable=False),
        sa.Column("body_hash", sa.String(length=128), nullable=False),
        sa.Column(
            "state",
            _enum("idempotency_state", "in_flight", "completed"),
            nullable=False,
        ),
        sa.Column("serialised_outcome", postgresql.BYTEA(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
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
    op.create_index(
        "ix_idempotency_records_expires_at",
        "idempotency_records",
        ["expires_at"],
    )


def downgrade() -> None:
    """Drop source-intake tables and intake-state columns."""
    op.drop_index(
        "ix_idempotency_records_expires_at",
        table_name="idempotency_records",
    )
    op.drop_table("idempotency_records")
    op.drop_index(
        "ix_ingestion_job_sources_upload_id",
        table_name="ingestion_job_sources",
    )
    op.drop_index(
        "ix_ingestion_job_sources_ingestion_job_id",
        table_name="ingestion_job_sources",
    )
    op.drop_table("ingestion_job_sources")
    op.drop_index("ix_uploads_state_created_at", table_name="uploads")
    op.drop_table("uploads")
    op.drop_index(
        "ix_ingestion_jobs_series_profile_intake_state_created_at",
        table_name="ingestion_jobs",
    )
    op.drop_column("ingestion_jobs", "intake_state")
    _enum("idempotency_state", "in_flight", "completed").drop(
        op.get_bind(),
        checkfirst=True,
    )
    _enum("attachment_kind", "upload", "source_uri").drop(
        op.get_bind(),
        checkfirst=True,
    )
    _enum("upload_state", "pending", "ready", "failed", "expired").drop(
        op.get_bind(),
        checkfirst=True,
    )
    _enum("intake_state", "awaiting_sources", "ready_for_generation", "cancelled").drop(
        op.get_bind(),
        checkfirst=True,
    )
