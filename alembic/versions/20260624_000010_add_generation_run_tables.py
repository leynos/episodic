"""Add durable generation-run and event-log tables."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260624_000010"
down_revision = "20260601_000009"
branch_labels = None
depends_on = None


def _enum(name: str, *values: str) -> postgresql.ENUM:
    """Return an existing-or-creatable PostgreSQL enum."""
    return postgresql.ENUM(*values, name=name, create_type=False)


def _create_enums() -> None:
    """Create generation-run PostgreSQL enums."""
    _enum(
        "generation_run_status",
        "pending",
        "running",
        "paused",
        "succeeded",
        "failed",
        "cancelled",
    ).create(op.get_bind(), checkfirst=True)
    _enum("quality_mode", "draft_without_qa").create(op.get_bind(), checkfirst=True)
    _enum("qa_status", "skipped").create(op.get_bind(), checkfirst=True)


def _drop_enums() -> None:
    """Drop generation-run PostgreSQL enums."""
    _enum("qa_status", "skipped").drop(op.get_bind(), checkfirst=True)
    _enum("quality_mode", "draft_without_qa").drop(op.get_bind(), checkfirst=True)
    _enum(
        "generation_run_status",
        "pending",
        "running",
        "paused",
        "succeeded",
        "failed",
        "cancelled",
    ).drop(op.get_bind(), checkfirst=True)


def _create_generation_runs_table() -> None:
    """Create durable generation-run records."""
    op.create_table(
        "generation_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("episode_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_bundle_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor", sa.String(length=240), nullable=False),
        sa.Column(
            "status",
            _enum(
                "generation_run_status",
                "pending",
                "running",
                "paused",
                "succeeded",
                "failed",
                "cancelled",
            ),
            nullable=False,
        ),
        sa.Column("current_node", sa.String(length=160), nullable=True),
        sa.Column("budget_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("configuration", postgresql.JSONB(), nullable=False),
        sa.Column(
            "quality_mode",
            _enum("quality_mode", "draft_without_qa"),
            nullable=False,
        ),
        sa.Column("qa_status", _enum("qa_status", "skipped"), nullable=True),
        sa.Column("skip_qa_rationale", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=512), nullable=True, unique=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("error_category", sa.String(length=120), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_generation_runs_episode_id",
        "generation_runs",
        ["episode_id"],
    )
    op.create_index("ix_generation_runs_status", "generation_runs", ["status"])
    op.create_index(
        "ix_generation_runs_started_at",
        "generation_runs",
        ["started_at"],
    )


def _drop_generation_runs_table() -> None:
    """Drop durable generation-run records."""
    op.drop_index("ix_generation_runs_started_at", table_name="generation_runs")
    op.drop_index("ix_generation_runs_status", table_name="generation_runs")
    op.drop_index("ix_generation_runs_episode_id", table_name="generation_runs")
    op.drop_table("generation_runs")


def _create_generation_events_table() -> None:
    """Create append-only generation-run event records."""
    op.create_table(
        "generation_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "generation_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("generation_runs.id"),
            nullable=False,
        ),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=160), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "generation_run_id",
            "seq",
            name="uq_generation_events_run_seq",
        ),
    )
    op.create_index(
        "ix_generation_events_generation_run_id",
        "generation_events",
        ["generation_run_id"],
    )


def _drop_generation_events_table() -> None:
    """Drop append-only generation-run event records."""
    op.drop_index(
        "ix_generation_events_generation_run_id",
        table_name="generation_events",
    )
    op.drop_table("generation_events")


def upgrade() -> None:
    """Create generation-run persistence tables."""
    _create_enums()
    _create_generation_runs_table()
    _create_generation_events_table()


def downgrade() -> None:
    """Drop generation-run persistence tables."""
    _drop_generation_events_table()
    _drop_generation_runs_table()
    _drop_enums()
