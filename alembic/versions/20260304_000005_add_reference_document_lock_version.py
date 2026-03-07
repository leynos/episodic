"""Add optimistic-lock column for reusable reference documents."""

import sqlalchemy as sa

from alembic import op

revision = "20260304_000005"
down_revision = "20260228_000004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply schema changes."""
    op.add_column(
        "reference_documents",
        sa.Column(
            "lock_version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
    )


def downgrade() -> None:
    """Revert schema changes."""
    op.drop_column("reference_documents", "lock_version")
