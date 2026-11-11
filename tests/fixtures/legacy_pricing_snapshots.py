"""The deployed pricing-snapshot schema shared by migration tests.

Both pricing migration suites seed and inspect the pre-content-address table.
Keeping the table definition and its revision here means a schema change is
made once, rather than in two copies that could drift apart silently.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

#: The revision immediately before the content-address migration.
LEGACY_REVISION = "20261031_000016"

LEGACY_TABLE = sa.table(
    "pricing_snapshots",
    sa.column("id", postgresql.UUID(as_uuid=True)),
    sa.column("provider_name", sa.Text),
    sa.column("model", sa.Text),
    sa.column("operation", sa.Text),
    sa.column("source_kind", sa.Text),
    sa.column("currency", sa.String(3)),
    sa.column("billing_period_key", sa.Text),
    sa.column("rates_minor_per_metric", postgresql.JSONB),
    sa.column("source_metadata", postgresql.JSONB),
    sa.column("content_hash", sa.Text),
    sa.column("retrieved_at", sa.DateTime(timezone=True)),
    sa.column("effective_from", sa.DateTime(timezone=True)),
)
