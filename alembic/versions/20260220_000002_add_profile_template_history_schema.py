"""Add profile/template and change-history tables for structured briefs.

This migration introduces:

- episode_templates
- series_profile_history
- episode_template_history
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260220_000002"
down_revision = "20260203_000001"
branch_labels = None
depends_on = None


def _create_episode_templates_table() -> None:
    """Create the episode templates table and indexes."""
    op.create_table(
        "episode_templates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "series_profile_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("series_profiles.id"),
            nullable=False,
        ),
        sa.Column("slug", sa.String(160), nullable=False),
        sa.Column("title", sa.String(240), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("structure", postgresql.JSONB(), nullable=False),
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
        sa.UniqueConstraint(
            "series_profile_id",
            "slug",
            name="uq_episode_templates_series_slug",
        ),
    )
    op.create_index(
        "ix_episode_templates_series_profile_id",
        "episode_templates",
        ["series_profile_id"],
    )


def _create_series_profile_history_table() -> None:
    """Create the series profile history table and indexes."""
    op.create_table(
        "series_profile_history",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "series_profile_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("series_profiles.id"),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("actor", sa.String(200), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("snapshot", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "series_profile_id",
            "revision",
            name="uq_series_profile_history_revision",
        ),
        sa.CheckConstraint(
            "revision >= 1",
            name="ck_series_profile_history_revision_positive",
        ),
    )
    op.create_index(
        "ix_series_profile_history_series_profile_id",
        "series_profile_history",
        ["series_profile_id"],
    )


def _create_episode_template_history_table() -> None:
    """Create the episode template history table and indexes."""
    op.create_table(
        "episode_template_history",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "episode_template_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("episode_templates.id"),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("actor", sa.String(200), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("snapshot", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "episode_template_id",
            "revision",
            name="uq_episode_template_history_revision",
        ),
        sa.CheckConstraint(
            "revision >= 1",
            name="ck_episode_template_history_revision_positive",
        ),
    )
    op.create_index(
        "ix_episode_template_history_episode_template_id",
        "episode_template_history",
        ["episode_template_id"],
    )


def _drop_episode_template_history_table() -> None:
    """Drop the episode template history table and indexes."""
    op.drop_index(
        "ix_episode_template_history_episode_template_id",
        table_name="episode_template_history",
    )
    op.drop_table("episode_template_history")


def _drop_series_profile_history_table() -> None:
    """Drop the series profile history table and indexes."""
    op.drop_index(
        "ix_series_profile_history_series_profile_id",
        table_name="series_profile_history",
    )
    op.drop_table("series_profile_history")


def _drop_episode_templates_table() -> None:
    """Drop the episode templates table and indexes."""
    op.drop_index(
        "ix_episode_templates_series_profile_id",
        table_name="episode_templates",
    )
    op.drop_table("episode_templates")


def upgrade() -> None:
    """Apply schema changes."""
    _create_episode_templates_table()
    _create_series_profile_history_table()
    _create_episode_template_history_table()


def downgrade() -> None:
    """Revert schema changes."""
    _drop_episode_template_history_table()
    _drop_series_profile_history_table()
    _drop_episode_templates_table()
