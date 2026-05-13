"""Add workflow checkpoints for resumable orchestration."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260508_000008"
down_revision = "20260322_000007"
branch_labels = None
depends_on = None


def _workflow_checkpoint_status_enum() -> postgresql.ENUM:
    return postgresql.ENUM(
        "suspended",
        "resumed",
        name="workflow_checkpoint_status",
        create_type=False,
    )


def upgrade() -> None:
    """Create the workflow_checkpoints table."""
    _workflow_checkpoint_status_enum().create(op.get_bind(), checkfirst=True)
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
            _workflow_checkpoint_status_enum(),
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
    op.execute(
        """
        CREATE FUNCTION update_workflow_checkpoints_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER update_workflow_checkpoints_updated_at
        BEFORE UPDATE ON workflow_checkpoints
        FOR EACH ROW
        EXECUTE FUNCTION update_workflow_checkpoints_updated_at();
        """
    )


def downgrade() -> None:
    """Drop the workflow_checkpoints table."""
    op.execute(
        "DROP TRIGGER IF EXISTS update_workflow_checkpoints_updated_at "
        "ON workflow_checkpoints;"
    )
    op.execute("DROP FUNCTION IF EXISTS update_workflow_checkpoints_updated_at();")
    op.drop_index(
        "ix_workflow_checkpoints_workflow_id",
        table_name="workflow_checkpoints",
    )
    op.drop_table("workflow_checkpoints")
    _workflow_checkpoint_status_enum().drop(op.get_bind(), checkfirst=True)
