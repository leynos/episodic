"""Add the per-attempt generation-run claim token.

The launcher's pending-to-running compare-and-set records a unique token for
the attempt that won. If a cancellation interrupts the commit acknowledgement,
the launcher reconciles the durable row against this token instead of guessing
from the start timestamp. The column is nullable: rows created before this
revision, and rows that were never claimed, keep ``NULL``.

Revision ID: 20261123_000019
Revises: 20261122_000018
Create Date: 2026-11-23
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20261123_000019"
down_revision = "20261122_000018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the nullable claim token column."""
    op.add_column(
        "generation_runs",
        sa.Column(
            "claim_token",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    """Remove the claim token column."""
    op.drop_column("generation_runs", "claim_token")
