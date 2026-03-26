"""Add reference_document_revision_id to source_documents table."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260322_000007"
down_revision = "20260309_000005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add nullable reference_document_revision_id foreign key column."""
    op.add_column(
        "source_documents",
        sa.Column(
            "reference_document_revision_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("reference_document_revisions.id"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_source_documents_reference_document_revision_id",
        "source_documents",
        ["reference_document_revision_id"],
    )


def downgrade() -> None:
    """Remove reference_document_revision_id column and index."""
    op.drop_index(
        "ix_source_documents_reference_document_revision_id",
        table_name="source_documents",
    )
    op.drop_column("source_documents", "reference_document_revision_id")
