"""SQLAlchemy models for cost accounting persistence."""

import datetime as dt  # ruff: ignore[typing-only-standard-library-import]  # SQLAlchemy evaluates annotations at runtime.
import uuid  # ruff: ignore[typing-only-standard-library-import]  # SQLAlchemy evaluates annotations at runtime.

import sqlalchemy as sa
from sqlalchemy import orm
from sqlalchemy.dialects import postgresql

from episodic.cost.ports import LedgerScope
from episodic.cost.pricing_snapshot import PricedService
from episodic.cost.primitives import PricingSourceKind
from episodic.sqlalchemy_base import Base

_SERVICE_KINDS = tuple(kind.value for kind in PricedService)
_SOURCE_KINDS = tuple(kind.value for kind in PricingSourceKind)


class PricingSnapshotRecord(Base):
    """Persisted immutable pricing snapshot."""

    __tablename__ = "pricing_snapshots"
    __table_args__ = (
        sa.UniqueConstraint(
            "content_hash",
            name="uq_pricing_snapshots_content_hash",
        ),
        sa.CheckConstraint(
            "schema_version = 1",
            name="ck_pricing_snapshots_schema_version",
        ),
        sa.CheckConstraint(
            sa.column("service_kind").in_(_SERVICE_KINDS),
            name="ck_pricing_snapshots_service_kind",
        ),
        sa.CheckConstraint(
            sa.column("source_kind").in_(_SOURCE_KINDS),
            name="ck_pricing_snapshots_source_kind",
        ),
        sa.CheckConstraint(
            "(source_document_media_type IS NULL) = (source_document_content IS NULL)",
            name="ck_pricing_snapshots_source_document_pair",
        ),
        sa.CheckConstraint(
            "source_kind <> 'sla4oai_plan' OR source_document_content IS NOT NULL",
            name="ck_pricing_snapshots_source_document_required",
        ),
    )

    id: orm.Mapped[uuid.UUID] = orm.mapped_column(
        postgresql.UUID(as_uuid=True),
        primary_key=True,
    )
    schema_version: orm.Mapped[int] = orm.mapped_column(sa.Integer, nullable=False)
    service_kind: orm.Mapped[str] = orm.mapped_column(sa.Text, nullable=False)
    provider_name: orm.Mapped[str] = orm.mapped_column(sa.Text, nullable=False)
    model: orm.Mapped[str] = orm.mapped_column(sa.Text, nullable=False)
    operation: orm.Mapped[str] = orm.mapped_column(sa.Text, nullable=False)
    source_kind: orm.Mapped[str] = orm.mapped_column(sa.Text, nullable=False)
    currency: orm.Mapped[str] = orm.mapped_column(sa.String(3), nullable=False)
    rates: orm.Mapped[dict[str, object]] = orm.mapped_column(
        postgresql.JSONB,
        nullable=False,
    )
    source_metadata: orm.Mapped[dict[str, object]] = orm.mapped_column(
        postgresql.JSONB,
        nullable=False,
    )
    retrieved_at: orm.Mapped[dt.datetime] = orm.mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
    )
    effective_from: orm.Mapped[dt.datetime | None] = orm.mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
    )
    source_document_media_type: orm.Mapped[str | None] = orm.mapped_column(
        sa.Text,
        nullable=True,
    )
    source_document_content: orm.Mapped[str | None] = orm.mapped_column(
        sa.Text,
        nullable=True,
    )
    content_hash: orm.Mapped[str] = orm.mapped_column(
        sa.Text,
        nullable=False,
    )
    recorded_at: orm.Mapped[dt.datetime] = orm.mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )


class CostLedgerEntryRecord(Base):
    """Persisted provider-call or task roll-up ledger row."""

    __tablename__ = "cost_ledger_entries"
    __table_args__ = (
        sa.Index(
            "ix_cost_ledger_entries_workflow_run_id",
            "workflow_run_id",
        ),
        sa.Index(
            "ix_cost_ledger_entries_workflow_run_scope",
            "workflow_run_id",
            "scope",
            postgresql_where=sa.column("scope").in_((
                LedgerScope.PROVIDER_CALL.value,
                LedgerScope.TASK.value,
            )),
        ),
    )

    id: orm.Mapped[uuid.UUID] = orm.mapped_column(
        postgresql.UUID(as_uuid=True),
        primary_key=True,
    )
    idempotency_key: orm.Mapped[str] = orm.mapped_column(
        sa.Text,
        nullable=False,
        unique=True,
    )
    parent_cost_entry_id: orm.Mapped[uuid.UUID | None] = orm.mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("cost_ledger_entries.id", ondelete="SET NULL"),
        nullable=True,
    )
    scope: orm.Mapped[LedgerScope] = orm.mapped_column(sa.Text, nullable=False)
    provider_type: orm.Mapped[str] = orm.mapped_column(sa.Text, nullable=False)
    provider_name: orm.Mapped[str] = orm.mapped_column(sa.Text, nullable=False)
    workflow_node: orm.Mapped[str | None] = orm.mapped_column(sa.Text, nullable=True)
    operation: orm.Mapped[str] = orm.mapped_column(sa.Text, nullable=False)
    pricing_snapshot_id: orm.Mapped[uuid.UUID | None] = orm.mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("pricing_snapshots.id", ondelete="RESTRICT"),
        nullable=True,
    )
    usage: orm.Mapped[dict[str, object]] = orm.mapped_column(
        postgresql.JSONB,
        nullable=False,
    )
    usage_source: orm.Mapped[str] = orm.mapped_column(sa.Text, nullable=False)
    usage_complete: orm.Mapped[bool] = orm.mapped_column(sa.Boolean, nullable=False)
    computed_cost_minor: orm.Mapped[int] = orm.mapped_column(
        sa.BigInteger,
        nullable=False,
    )
    currency: orm.Mapped[str] = orm.mapped_column(sa.String(3), nullable=False)
    pricing_model: orm.Mapped[str] = orm.mapped_column(sa.Text, nullable=False)
    retry_attempt: orm.Mapped[int] = orm.mapped_column(sa.Integer, nullable=False)
    billing_period_key: orm.Mapped[str] = orm.mapped_column(sa.Text, nullable=False)
    workflow_run_id: orm.Mapped[str] = orm.mapped_column(
        sa.Text,
        nullable=False,
    )
    recorded_at: orm.Mapped[dt.datetime] = orm.mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
    )


class MeteringCounterRecord(Base):
    """Current consumed total for one metering counter and billing period."""

    __tablename__ = "metering_counters"

    counter_key: orm.Mapped[str] = orm.mapped_column(sa.Text, primary_key=True)
    billing_period_key: orm.Mapped[str] = orm.mapped_column(sa.Text, primary_key=True)
    consumed: orm.Mapped[int] = orm.mapped_column(sa.BigInteger, nullable=False)
    # The database trigger owns update timestamps so ad-hoc SQL and ORM writes
    # follow the same rule.
    updated_at: orm.Mapped[dt.datetime] = orm.mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )


class MeteringCounterEventRecord(Base):
    """Idempotency audit event for metering consumption."""

    __tablename__ = "metering_counter_events"

    idempotency_key: orm.Mapped[str] = orm.mapped_column(sa.Text, primary_key=True)
    counter_key: orm.Mapped[str] = orm.mapped_column(sa.Text, nullable=False)
    billing_period_key: orm.Mapped[str] = orm.mapped_column(sa.Text, nullable=False)
    delta: orm.Mapped[int] = orm.mapped_column(sa.BigInteger, nullable=False)
    consumed_after: orm.Mapped[int] = orm.mapped_column(sa.BigInteger, nullable=False)
    recorded_at: orm.Mapped[dt.datetime] = orm.mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )


class RunPricingPinRecord(Base):
    """Pricing snapshot pinned for one workflow run and provider operation."""

    __tablename__ = "run_pricing_pins"

    workflow_run_id: orm.Mapped[str] = orm.mapped_column(sa.Text, primary_key=True)
    provider_name: orm.Mapped[str] = orm.mapped_column(sa.Text, primary_key=True)
    model: orm.Mapped[str] = orm.mapped_column(sa.Text, primary_key=True)
    operation: orm.Mapped[str] = orm.mapped_column(sa.Text, primary_key=True)
    billing_period_key: orm.Mapped[str] = orm.mapped_column(sa.Text, primary_key=True)
    pricing_snapshot_id: orm.Mapped[uuid.UUID] = orm.mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("pricing_snapshots.id", ondelete="RESTRICT"),
        nullable=False,
    )
    pinned_at: orm.Mapped[dt.datetime] = orm.mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )
