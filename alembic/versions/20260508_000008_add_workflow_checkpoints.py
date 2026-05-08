"""Add workflow checkpoints for resumable orchestration."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260508_000008"
down_revision = "20260322_000007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the workflow_checkpoints table."""
    op.create_table(
        "workflow_checkpoints",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("workflow_id", sa.String(length=160), nullable=False),
        sa.Column("workflow_type", sa.String(length=120), nullable=False),
        sa.Column("step_name", sa.String(length=120), nullable=False),
        sa.Column("idempotency_key", sa.String(length=512), nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column(
            "status",
            sa.String(length=80),
            server_default="suspended",
            nullable=False,
        ),
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
        sa.UniqueConstraint(
            "idempotency_key",
            name="uq_workflow_checkpoints_idempotency_key",
        ),
    )
    op.create_index(
        "ix_workflow_checkpoints_workflow_id",
        "workflow_checkpoints",
        ["workflow_id"],
    )


def downgrade() -> None:
    """Drop the workflow_checkpoints table."""
    op.drop_index(
        "ix_workflow_checkpoints_workflow_id",
        table_name="workflow_checkpoints",
    )
    op.drop_table("workflow_checkpoints")
