"""Add an authenticated-principal owner to ingestion jobs."""

import sqlalchemy as sa

from alembic import op

revision = "20260624_000012"
down_revision = "20260624_000011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Persist optional ownership for jobs created before authentication."""
    op.add_column(
        "ingestion_jobs",
        sa.Column("owner_principal_id", sa.String(length=240), nullable=True),
    )
    op.create_index(
        "ix_ij_owner_created",
        "ingestion_jobs",
        ["owner_principal_id", "created_at", "id"],
    )


def downgrade() -> None:
    """Remove ingestion-job ownership."""
    op.drop_index("ix_ij_owner_created", "ingestion_jobs")
    op.drop_column("ingestion_jobs", "owner_principal_id")
