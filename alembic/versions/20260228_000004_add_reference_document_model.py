"""Add reusable reference-document tables and enum types.

This migration introduces canonical reusable-reference tables:

- reference_documents
- reference_document_revisions
- reference_document_bindings
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260228_000004"
down_revision = "20260226_000003"
branch_labels = None
depends_on = None


def _reference_document_kind_enum() -> postgresql.ENUM:
    return postgresql.ENUM(
        "style_guide",
        "host_profile",
        "guest_profile",
        "research_brief",
        name="reference_document_kind",
        create_type=False,
    )


def _reference_document_lifecycle_state_enum() -> postgresql.ENUM:
    return postgresql.ENUM(
        "draft",
        "active",
        "archived",
        name="reference_document_lifecycle_state",
        create_type=False,
    )


def _reference_binding_target_kind_enum() -> postgresql.ENUM:
    return postgresql.ENUM(
        "series_profile",
        "episode_template",
        "ingestion_job",
        name="reference_binding_target_kind",
        create_type=False,
    )


def upgrade() -> None:
    """Apply schema changes."""
    bind = op.get_bind()
    _reference_document_kind_enum().create(bind, checkfirst=True)
    _reference_document_lifecycle_state_enum().create(bind, checkfirst=True)
    _reference_binding_target_kind_enum().create(bind, checkfirst=True)

    op.create_table(
        "reference_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "owner_series_profile_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("series_profiles.id"),
            nullable=False,
        ),
        sa.Column("kind", _reference_document_kind_enum(), nullable=False),
        sa.Column(
            "lifecycle_state",
            _reference_document_lifecycle_state_enum(),
            nullable=False,
        ),
        sa.Column("metadata", postgresql.JSONB(), nullable=False),
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
    )
    op.create_index(
        "ix_reference_documents_owner_series_profile_id",
        "reference_documents",
        ["owner_series_profile_id"],
    )

    op.create_table(
        "reference_document_revisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "reference_document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("reference_documents.id"),
            nullable=False,
        ),
        sa.Column("content", postgresql.JSONB(), nullable=False),
        sa.Column("content_hash", sa.String(128), nullable=False),
        sa.Column("author", sa.String(200), nullable=True),
        sa.Column("change_note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "reference_document_id",
            "content_hash",
            name="uq_reference_document_revisions_document_hash",
        ),
    )
    op.create_index(
        "ix_reference_document_revisions_reference_document_id",
        "reference_document_revisions",
        ["reference_document_id"],
    )

    op.create_table(
        "reference_document_bindings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "reference_document_revision_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("reference_document_revisions.id"),
            nullable=False,
        ),
        sa.Column(
            "target_kind",
            _reference_binding_target_kind_enum(),
            nullable=False,
        ),
        sa.Column(
            "series_profile_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("series_profiles.id"),
            nullable=True,
        ),
        sa.Column(
            "episode_template_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("episode_templates.id"),
            nullable=True,
        ),
        sa.Column(
            "ingestion_job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ingestion_jobs.id"),
            nullable=True,
        ),
        sa.Column(
            "effective_from_episode_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("episodes.id"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "((target_kind = 'series_profile' AND series_profile_id IS NOT NULL "
            "AND episode_template_id IS NULL AND ingestion_job_id IS NULL) OR "
            "(target_kind = 'episode_template' AND episode_template_id IS NOT NULL "
            "AND series_profile_id IS NULL AND ingestion_job_id IS NULL) OR "
            "(target_kind = 'ingestion_job' AND ingestion_job_id IS NOT NULL "
            "AND series_profile_id IS NULL AND episode_template_id IS NULL))",
            name="ck_reference_document_bindings_target",
        ),
        sa.CheckConstraint(
            "(effective_from_episode_id IS NULL OR target_kind = 'series_profile')",
            name="ck_reference_document_bindings_effective_episode",
        ),
        sa.UniqueConstraint(
            "reference_document_revision_id",
            "target_kind",
            "series_profile_id",
            "episode_template_id",
            "ingestion_job_id",
            "effective_from_episode_id",
            name="uq_reference_document_bindings_target_revision",
        ),
    )
    op.create_index(
        "ix_reference_document_bindings_reference_document_revision_id",
        "reference_document_bindings",
        ["reference_document_revision_id"],
    )
    op.create_index(
        "ix_reference_document_bindings_series_profile_id",
        "reference_document_bindings",
        ["series_profile_id"],
    )
    op.create_index(
        "ix_reference_document_bindings_episode_template_id",
        "reference_document_bindings",
        ["episode_template_id"],
    )
    op.create_index(
        "ix_reference_document_bindings_ingestion_job_id",
        "reference_document_bindings",
        ["ingestion_job_id"],
    )


def downgrade() -> None:
    """Revert schema changes."""
    op.drop_index(
        "ix_reference_document_bindings_ingestion_job_id",
        table_name="reference_document_bindings",
    )
    op.drop_index(
        "ix_reference_document_bindings_episode_template_id",
        table_name="reference_document_bindings",
    )
    op.drop_index(
        "ix_reference_document_bindings_series_profile_id",
        table_name="reference_document_bindings",
    )
    op.drop_index(
        "ix_reference_document_bindings_reference_document_revision_id",
        table_name="reference_document_bindings",
    )
    op.drop_table("reference_document_bindings")

    op.drop_index(
        "ix_reference_document_revisions_reference_document_id",
        table_name="reference_document_revisions",
    )
    op.drop_table("reference_document_revisions")

    op.drop_index(
        "ix_reference_documents_owner_series_profile_id",
        table_name="reference_documents",
    )
    op.drop_table("reference_documents")

    bind = op.get_bind()
    _reference_binding_target_kind_enum().drop(bind, checkfirst=True)
    _reference_document_lifecycle_state_enum().drop(bind, checkfirst=True)
    _reference_document_kind_enum().drop(bind, checkfirst=True)
