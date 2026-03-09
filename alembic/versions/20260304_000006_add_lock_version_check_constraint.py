"""Add CHECK constraint for lock_version on reference_documents."""

from alembic import op

revision = "20260304_000006"
down_revision = "20260304_000005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply schema changes."""
    op.create_check_constraint(
        "ck_reference_documents_lock_version_positive",
        "reference_documents",
        "lock_version >= 1",
    )


def downgrade() -> None:
    """Revert schema changes."""
    op.drop_constraint(
        "ck_reference_documents_lock_version_positive",
        "reference_documents",
        type_="check",
    )
