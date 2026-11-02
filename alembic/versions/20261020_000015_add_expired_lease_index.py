"""Add the partial index backing expired-lease reclamation.

Dropping this revision drops only an index; no row and no column is lost, so a
downgrade costs query time rather than data.

The index is partial on ``status = 'running'``: a run holds an execution lease
only while it is running, so the predicate keeps the index small as terminal
runs accumulate without bound.

The name and predicate are spelled out here rather than imported from
``generation_run_schema``. A revision records the schema as it was applied, so
editing the ORM declaration must not rewrite history. Guarding the duplication
is instead the job of
``tests/canonical_storage/test_expired_lease_index_definition.py``, which reads
the deployed index back from PostgreSQL and fails when it no longer matches
that declaration.
"""

import sqlalchemy as sa

from alembic import op

revision = "20261020_000015"
down_revision = "20261020_000014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the expired-lease partial index."""
    op.create_index(
        "ix_generation_runs_expired_lease",
        "generation_runs",
        ["lease_expires_at"],
        postgresql_where=sa.text("status = 'running'"),
    )


def downgrade() -> None:
    """Drop the expired-lease partial index."""
    op.drop_index(
        "ix_generation_runs_expired_lease",
        table_name="generation_runs",
    )
