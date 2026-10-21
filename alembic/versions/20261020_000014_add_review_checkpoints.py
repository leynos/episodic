"""Add durable review-checkpoint records.

Data loss: downgrading this revision drops ``review_checkpoints`` and destroys
every reviewer decision recorded in it. Nothing reconstructs a response from
another table, so take a backup before rolling back in production.

The foreign key is ``ON DELETE RESTRICT`` rather than ``CASCADE``, per ADR-018's
audit-trail deletion policy: a generation run cannot be deleted out from under a
reviewer's decision.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20261020_000014"
down_revision = "20261010_000013"
branch_labels = None
depends_on = None


def _enum(name: str, *values: str) -> postgresql.ENUM:
    """Return an existing-or-creatable PostgreSQL enum."""
    return postgresql.ENUM(*values, name=name, create_type=False)


def _create_enums() -> None:
    """Create review-checkpoint PostgreSQL enums."""
    _enum(
        "review_checkpoint_status",
        "created",
        "responded",
        "timed_out",
        "cancelled",
    ).create(op.get_bind(), checkfirst=True)
    _enum(
        "review_checkpoint_action",
        "approve",
        "request_changes",
        "edit",
    ).create(op.get_bind(), checkfirst=True)


def _drop_enums() -> None:
    """Drop review-checkpoint PostgreSQL enums."""
    _enum(
        "review_checkpoint_action",
        "approve",
        "request_changes",
        "edit",
    ).drop(op.get_bind(), checkfirst=True)
    _enum(
        "review_checkpoint_status",
        "created",
        "responded",
        "timed_out",
        "cancelled",
    ).drop(op.get_bind(), checkfirst=True)


def _create_review_checkpoint_indexes() -> None:
    """Create the review-checkpoint lookup indexes."""
    op.create_index(
        "ix_review_checkpoints_run_status",
        "review_checkpoints",
        ["generation_run_id", "status"],
    )
    # Partial: only live checkpoints are indexed, so the index stays small as
    # terminal rows accumulate without bound. No standalone index on `status`,
    # which has four values and would be seq-scanned past.
    op.create_index(
        "ix_review_checkpoints_open",
        "review_checkpoints",
        ["generation_run_id"],
        postgresql_where=sa.text("status = 'created'"),
    )


def _create_review_checkpoints_table() -> None:
    """Create durable reviewer checkpoint records."""
    op.create_table(
        "review_checkpoints",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "generation_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("generation_runs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("node", sa.String(length=160), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("options", postgresql.JSONB(), nullable=False),
        sa.Column(
            "status",
            _enum(
                "review_checkpoint_status",
                "created",
                "responded",
                "timed_out",
                "cancelled",
            ),
            nullable=False,
        ),
        sa.Column(
            "response_action",
            _enum("review_checkpoint_action", "approve", "request_changes", "edit"),
            nullable=True,
        ),
        sa.Column(
            "response_payload",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("responded_by", sa.String(length=240), nullable=True),
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
        sa.CheckConstraint(
            "jsonb_typeof(options) = 'array' AND jsonb_array_length(options) > 0",
            name="ck_review_checkpoints_options_array",
        ),
        sa.CheckConstraint(
            "status <> 'responded' OR ("
            " response_action IS NOT NULL"
            " AND responded_by IS NOT NULL"
            " AND resolved_at IS NOT NULL)",
            name="ck_review_checkpoints_responded_fields",
        ),
    )
    _create_review_checkpoint_indexes()


def _drop_review_checkpoints_table() -> None:
    """Drop durable reviewer checkpoint records."""
    op.drop_index("ix_review_checkpoints_open", table_name="review_checkpoints")
    op.drop_index(
        "ix_review_checkpoints_run_status",
        table_name="review_checkpoints",
    )
    op.drop_table("review_checkpoints")


def upgrade() -> None:
    """Create review-checkpoint persistence tables."""
    _create_enums()
    _create_review_checkpoints_table()


def downgrade() -> None:
    """Drop review-checkpoint persistence tables."""
    _drop_review_checkpoints_table()
    _drop_enums()
