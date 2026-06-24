"""Add episode TEI revision metadata."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260624_000011"
down_revision = "20260624_000010"
branch_labels = None
depends_on = None


def _qa_status_enum() -> postgresql.ENUM:
    """Return the existing QA status PostgreSQL enum."""
    return postgresql.ENUM("skipped", name="qa_status", create_type=False)


def upgrade() -> None:
    """Add optimistic TEI revision metadata to episodes."""
    op.add_column(
        "episodes",
        sa.Column("tei_revision", sa.Integer(), server_default="1", nullable=False),
    )
    op.add_column(
        "episodes",
        sa.Column("tei_content_hash", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "episodes",
        sa.Column("qa_status", _qa_status_enum(), nullable=True),
    )
    op.add_column(
        "episodes",
        sa.Column(
            "last_generation_run_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_episodes_last_generation_run_id_generation_runs",
        "episodes",
        "generation_runs",
        ["last_generation_run_id"],
        ["id"],
    )


def downgrade() -> None:
    """Remove optimistic TEI revision metadata from episodes."""
    op.drop_constraint(
        "fk_episodes_last_generation_run_id_generation_runs",
        "episodes",
        type_="foreignkey",
    )
    op.drop_column("episodes", "last_generation_run_id")
    op.drop_column("episodes", "qa_status")
    op.drop_column("episodes", "tei_content_hash")
    op.drop_column("episodes", "tei_revision")
