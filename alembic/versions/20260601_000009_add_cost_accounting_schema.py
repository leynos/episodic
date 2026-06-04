"""Add cost accounting schema."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260601_000009"
down_revision = "20260508_000008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create cost accounting tables."""
    op.create_table(
        "pricing_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("provider_name", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("operation", sa.Text(), nullable=False),
        sa.Column("source_kind", sa.Text(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("billing_period_key", sa.Text(), nullable=False),
        sa.Column("rates_minor_per_metric", postgresql.JSONB(), nullable=False),
        sa.Column("source_metadata", postgresql.JSONB(), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False, unique=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "cost_ledger_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("idempotency_key", sa.Text(), nullable=False, unique=True),
        sa.Column("parent_cost_entry_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("provider_type", sa.Text(), nullable=False),
        sa.Column("provider_name", sa.Text(), nullable=False),
        sa.Column("workflow_node", sa.Text(), nullable=True),
        sa.Column("operation", sa.Text(), nullable=False),
        sa.Column("pricing_snapshot_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("usage", postgresql.JSONB(), nullable=False),
        sa.Column("usage_source", sa.Text(), nullable=False),
        sa.Column("usage_complete", sa.Boolean(), nullable=False),
        sa.Column("computed_cost_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("pricing_model", sa.Text(), nullable=False),
        sa.Column("retry_attempt", sa.Integer(), nullable=False),
        sa.Column("billing_period_key", sa.Text(), nullable=False),
        sa.Column("workflow_run_id", sa.Text(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["parent_cost_entry_id"],
            ["cost_ledger_entries.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["pricing_snapshot_id"],
            ["pricing_snapshots.id"],
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "ix_cost_ledger_entries_workflow_run_id",
        "cost_ledger_entries",
        ["workflow_run_id"],
    )
    op.create_index(
        "ix_cost_ledger_entries_workflow_run_scope",
        "cost_ledger_entries",
        ["workflow_run_id", "scope"],
        postgresql_where=sa.text("scope IN ('provider_call', 'task')"),
    )
    op.create_table(
        "metering_counters",
        sa.Column("counter_key", sa.Text(), primary_key=True),
        sa.Column("billing_period_key", sa.Text(), primary_key=True),
        sa.Column("consumed", sa.BigInteger(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_table(
        "metering_counter_events",
        sa.Column("idempotency_key", sa.Text(), primary_key=True),
        sa.Column("counter_key", sa.Text(), nullable=False),
        sa.Column("billing_period_key", sa.Text(), nullable=False),
        sa.Column("delta", sa.BigInteger(), nullable=False),
        sa.Column("consumed_after", sa.BigInteger(), nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.execute(
        """
        CREATE FUNCTION update_metering_counters_updated_at()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_metering_counters_updated_at
        BEFORE UPDATE ON metering_counters
        FOR EACH ROW
        EXECUTE FUNCTION update_metering_counters_updated_at();
        """
    )
    op.create_table(
        "run_pricing_pins",
        sa.Column("workflow_run_id", sa.Text(), primary_key=True),
        sa.Column("provider_name", sa.Text(), primary_key=True),
        sa.Column("model", sa.Text(), primary_key=True),
        sa.Column("operation", sa.Text(), primary_key=True),
        sa.Column("billing_period_key", sa.Text(), primary_key=True),
        sa.Column("pricing_snapshot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "pinned_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["pricing_snapshot_id"],
            ["pricing_snapshots.id"],
            ondelete="RESTRICT",
        ),
    )


def downgrade() -> None:
    """Drop cost accounting tables."""
    op.drop_table("run_pricing_pins")
    op.drop_table("metering_counter_events")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_metering_counters_updated_at ON metering_counters"
    )
    op.execute("DROP FUNCTION IF EXISTS update_metering_counters_updated_at()")
    op.drop_table("metering_counters")
    op.drop_index(
        "ix_cost_ledger_entries_workflow_run_scope",
        table_name="cost_ledger_entries",
    )
    op.drop_index(
        "ix_cost_ledger_entries_workflow_run_id",
        table_name="cost_ledger_entries",
    )
    op.drop_table("cost_ledger_entries")
    op.drop_table("pricing_snapshots")
