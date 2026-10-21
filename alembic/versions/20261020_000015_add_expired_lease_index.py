"""Add the partial index backing expired-lease reclamation.

Dropping this revision drops only an index; no row and no column is lost, so a
downgrade costs query time rather than data.

The index is partial on ``status = 'running'``: a run holds an execution lease
only while it is running, so the predicate keeps the index small as terminal
runs accumulate without bound. ``GENERATION_RUN_EXPIRED_LEASE_PREDICATE_SQL`` is
imported rather than spelled out here because ``GenerationRunRecord`` mirrors
this index and the two declarations must not drift.
"""

import sqlalchemy as sa

from alembic import op
from episodic.canonical.storage.generation_run_schema import (
    GENERATION_RUN_EXPIRED_LEASE_INDEX,
    GENERATION_RUN_EXPIRED_LEASE_PREDICATE_SQL,
)

revision = "20261020_000015"
down_revision = "20261020_000014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the expired-lease partial index."""
    op.create_index(
        GENERATION_RUN_EXPIRED_LEASE_INDEX,
        "generation_runs",
        ["lease_expires_at"],
        postgresql_where=sa.text(GENERATION_RUN_EXPIRED_LEASE_PREDICATE_SQL),
    )


def downgrade() -> None:
    """Drop the expired-lease partial index."""
    op.drop_index(
        GENERATION_RUN_EXPIRED_LEASE_INDEX,
        table_name="generation_runs",
    )
