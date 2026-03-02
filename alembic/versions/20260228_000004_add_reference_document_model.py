"""Add reusable reference-document tables and enum types.

This migration introduces canonical reusable-reference tables:

- reference_documents
- reference_document_revisions
- reference_document_bindings
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from episodic.canonical.storage.reference_document_schema import (
    REFERENCE_BINDING_TARGET_KIND_VALUES,
    REFERENCE_BINDINGS_EFFECTIVE_EPISODE_CHECK_SQL,
    REFERENCE_BINDINGS_TARGET_CHECK_SQL,
    REFERENCE_DOCUMENT_KIND_VALUES,
    REFERENCE_DOCUMENT_LIFECYCLE_STATE_VALUES,
    TARGET_KIND_EPISODE_TEMPLATE,
    TARGET_KIND_INGESTION_JOB,
    TARGET_KIND_SERIES_PROFILE,
)

revision = "20260228_000004"
down_revision = "20260226_000003"
branch_labels = None
depends_on = None


def _reference_document_kind_enum() -> postgresql.ENUM:
    return postgresql.ENUM(
        *REFERENCE_DOCUMENT_KIND_VALUES,
        name="reference_document_kind",
        create_type=False,
    )


def _reference_document_lifecycle_state_enum() -> postgresql.ENUM:
    return postgresql.ENUM(
        *REFERENCE_DOCUMENT_LIFECYCLE_STATE_VALUES,
        name="reference_document_lifecycle_state",
        create_type=False,
    )


def _reference_binding_target_kind_enum() -> postgresql.ENUM:
    return postgresql.ENUM(
        *REFERENCE_BINDING_TARGET_KIND_VALUES,
        name="reference_binding_target_kind",
        create_type=False,
    )


def _create_reference_documents_table() -> None:
    """Create reference_documents table and owner_series_profile_id index."""
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


def _create_reference_document_revisions_table() -> None:
    """Create reference_document_revisions table and reference_document_id index."""
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


def _create_reference_document_bindings_table() -> None:
    """Create reference_document_bindings table with constraints."""
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
            REFERENCE_BINDINGS_TARGET_CHECK_SQL,
            name="ck_reference_document_bindings_target",
        ),
        sa.CheckConstraint(
            REFERENCE_BINDINGS_EFFECTIVE_EPISODE_CHECK_SQL,
            name="ck_reference_document_bindings_effective_episode",
        ),
    )


def _create_reference_document_bindings_indexes() -> None:
    """Create all target lookup indexes for reference_document_bindings."""
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
    op.create_index(
        "uq_ref_doc_bindings_series_rev_effective",
        "reference_document_bindings",
        [
            "reference_document_revision_id",
            "series_profile_id",
            "effective_from_episode_id",
        ],
        unique=True,
        postgresql_where=sa.text(
            f"target_kind = '{TARGET_KIND_SERIES_PROFILE}' "
            "AND effective_from_episode_id IS NOT NULL"
        ),
    )
    op.create_index(
        "uq_ref_doc_bindings_series_rev_no_effective",
        "reference_document_bindings",
        ["reference_document_revision_id", "series_profile_id"],
        unique=True,
        postgresql_where=sa.text(
            f"target_kind = '{TARGET_KIND_SERIES_PROFILE}' "
            "AND effective_from_episode_id IS NULL"
        ),
    )
    op.create_index(
        "uq_ref_doc_bindings_template_rev",
        "reference_document_bindings",
        ["reference_document_revision_id", "episode_template_id"],
        unique=True,
        postgresql_where=sa.text(f"target_kind = '{TARGET_KIND_EPISODE_TEMPLATE}'"),
    )
    op.create_index(
        "uq_ref_doc_bindings_job_rev",
        "reference_document_bindings",
        ["reference_document_revision_id", "ingestion_job_id"],
        unique=True,
        postgresql_where=sa.text(f"target_kind = '{TARGET_KIND_INGESTION_JOB}'"),
    )


def upgrade() -> None:
    """Apply schema changes."""
    bind = op.get_bind()
    _reference_document_kind_enum().create(bind, checkfirst=True)
    _reference_document_lifecycle_state_enum().create(bind, checkfirst=True)
    _reference_binding_target_kind_enum().create(bind, checkfirst=True)
    _create_reference_documents_table()
    _create_reference_document_revisions_table()
    _create_reference_document_bindings_table()
    _create_reference_document_bindings_indexes()


def downgrade() -> None:
    """Revert schema changes."""
    op.drop_index(
        "uq_ref_doc_bindings_job_rev",
        table_name="reference_document_bindings",
    )
    op.drop_index(
        "uq_ref_doc_bindings_template_rev",
        table_name="reference_document_bindings",
    )
    op.drop_index(
        "uq_ref_doc_bindings_series_rev_no_effective",
        table_name="reference_document_bindings",
    )
    op.drop_index(
        "uq_ref_doc_bindings_series_rev_effective",
        table_name="reference_document_bindings",
    )
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
