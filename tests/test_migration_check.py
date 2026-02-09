"""Unit tests for schema drift detection.

Examples
--------
Run migration drift detection tests:

>>> pytest tests/test_migration_check.py -v
"""

from __future__ import annotations

import typing as typ

import pytest
import sqlalchemy as sa

from episodic.canonical.storage import Base, detect_schema_drift

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine


@pytest.mark.asyncio
async def test_no_drift_when_models_match_migrations(
    migrated_engine: AsyncEngine,
) -> None:
    """Schema drift check reports no differences when models are in sync."""
    diffs = await detect_schema_drift(migrated_engine)
    assert diffs == [], f"Expected no schema drift, found: {diffs}"


@pytest.mark.asyncio
async def test_drift_detected_for_unmigrated_table(
    migrated_engine: AsyncEngine,
) -> None:
    """Schema drift check detects a table present in metadata but not in migrations."""
    table = sa.Table(
        "_test_drift_table",
        Base.metadata,
        sa.Column("id", sa.Integer, primary_key=True),
    )
    try:
        diffs = await detect_schema_drift(migrated_engine)
        assert len(diffs) > 0, "Expected schema drift to be detected."
    finally:
        Base.metadata.remove(table)
