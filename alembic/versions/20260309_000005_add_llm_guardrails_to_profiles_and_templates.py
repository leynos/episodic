"""Add persisted LLM guardrail JSON fields to profiles and templates."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260309_000005"
down_revision = "20260228_000004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add persisted guardrail JSON columns to profile/template tables."""
    empty_json = sa.text("'{}'::jsonb")
    op.add_column(
        "series_profiles",
        sa.Column(
            "guardrails",
            postgresql.JSONB(),
            nullable=False,
            server_default=empty_json,
        ),
    )
    op.add_column(
        "episode_templates",
        sa.Column(
            "guardrails",
            postgresql.JSONB(),
            nullable=False,
            server_default=empty_json,
        ),
    )


def downgrade() -> None:
    """Drop persisted guardrail JSON columns from profile/template tables."""
    op.drop_column("episode_templates", "guardrails")
    op.drop_column("series_profiles", "guardrails")
