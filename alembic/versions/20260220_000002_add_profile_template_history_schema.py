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


def _create_history_table(
    *,
    table_name: str,
    parent_fk_col: str,
    parent_fk_target: tuple[str, str],
    constraint_names: tuple[str, str],
) -> None:
    """Create a change-history table with shared column layout."""
    uq_name, ck_name = constraint_names
    op.create_table(
        table_name,
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            parent_fk_col,
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(f"{parent_fk_target[0]}.{parent_fk_target[1]}"),
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
        sa.UniqueConstraint(parent_fk_col, "revision", name=uq_name),
        sa.CheckConstraint("revision >= 1", name=ck_name),
    )
    op.create_index(
        f"ix_{table_name}_{parent_fk_col}",
        table_name,
        [parent_fk_col],
    )


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
    _create_history_table(
        table_name="series_profile_history",
        parent_fk_col="series_profile_id",
        parent_fk_target=("series_profiles", "id"),
        constraint_names=(
            "uq_series_profile_history_revision",
            "ck_series_profile_history_revision_positive",
        ),
    )


def _create_episode_template_history_table() -> None:
    """Create the episode template history table and indexes."""
    _create_history_table(
        table_name="episode_template_history",
        parent_fk_col="episode_template_id",
        parent_fk_target=("episode_templates", "id"),
        constraint_names=(
            "uq_episode_template_history_revision",
            "ck_episode_template_history_revision_positive",
        ),
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
