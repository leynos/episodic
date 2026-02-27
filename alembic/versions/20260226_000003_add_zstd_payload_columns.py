"""Add compressed TEI payload columns for storage-level Zstandard adoption.

This migration adds nullable binary columns used to store large TEI XML
payloads in compressed form while preserving backward-compatible reads from the
existing text columns.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260226_000003"
down_revision = "20260220_000002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply schema changes."""
    op.add_column(
        "tei_headers",
        sa.Column("raw_xml_zstd", postgresql.BYTEA(), nullable=True),
    )
    op.add_column(
        "episodes",
        sa.Column("tei_xml_zstd", postgresql.BYTEA(), nullable=True),
    )


def downgrade() -> None:
    """Revert schema changes."""
    op.drop_column("episodes", "tei_xml_zstd")
    op.drop_column("tei_headers", "raw_xml_zstd")
