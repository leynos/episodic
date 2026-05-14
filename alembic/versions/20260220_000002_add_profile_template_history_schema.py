"""Add profile/template and change-history tables for structured briefs.

This migration introduces:

- episode_templates
- series_profile_history
- episode_template_history
"""

from __future__ import annotations

import typing as typ

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260220_000002"
down_revision = "20260203_000001"
branch_labels = None
depends_on = None


class _HistorySpec(typ.NamedTuple):
    """Describe one change-history table."""

    table_name: str
    parent_fk_col: str
    parent_fk_target: tuple[str, str]
    constraint_names: tuple[str, str]


_HISTORY_SPECS = (
    _HistorySpec(
        table_name="series_profile_history",
        parent_fk_col="series_profile_id",
        parent_fk_target=("series_profiles", "id"),
        constraint_names=(
            "uq_series_profile_history_revision",
            "ck_series_profile_history_revision_positive",
        ),
    ),
    _HistorySpec(
        table_name="episode_template_history",
        parent_fk_col="episode_template_id",
        parent_fk_target=("episode_templates", "id"),
        constraint_names=(
            "uq_episode_template_history_revision",
            "ck_episode_template_history_revision_positive",
        ),
    ),
)


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


def _create_history_tables() -> None:
    """Create change-history tables in dependency order."""
    for spec in _HISTORY_SPECS:
        _create_history_table(**spec._asdict())


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


def _drop_history_tables() -> None:
    """Drop change-history tables in reverse dependency order."""
    for spec in reversed(_HISTORY_SPECS):
        op.drop_index(
            f"ix_{spec.table_name}_{spec.parent_fk_col}",
            table_name=spec.table_name,
        )
        op.drop_table(spec.table_name)


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
    _create_history_tables()


def downgrade() -> None:
    """Revert schema changes."""
    _drop_history_tables()
    _drop_episode_templates_table()
