"""Unit tests for schema drift detection.

Examples
--------
Run migration drift detection tests:

>>> pytest tests/test_migration_check.py -v
"""

import typing as typ

import pytest

from episodic.canonical.storage import detect_schema_drift
from tests.conftest import temporary_drift_table

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
    with temporary_drift_table():
        diffs = await detect_schema_drift(migrated_engine)
        assert len(diffs) > 0, "Expected schema drift to be detected."
