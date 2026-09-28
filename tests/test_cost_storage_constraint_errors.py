"""Tests for classifying pricing-snapshot database constraint errors."""

from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError

from episodic.cost.storage.adapters import _is_pricing_snapshot_hash_collision

_HASH_CONSTRAINT_ERROR = (
    'duplicate key value violates unique constraint "uq_pricing_snapshots_content_hash"'
)


class _DriverError(Exception):
    """Represent PostgreSQL exception metadata exposed by supported drivers."""

    constraint_name: str | None
    diag: SimpleNamespace | None

    def __init__(
        self,
        message: str,
        *,
        constraint_name: str | None = None,
        diagnostic_constraint_name: str | None = None,
    ) -> None:
        super().__init__(message)
        self.constraint_name = constraint_name
        self.diag = (
            SimpleNamespace(constraint_name=diagnostic_constraint_name)
            if diagnostic_constraint_name is not None
            else None
        )


def test_hash_collision_uses_asyncpg_constraint_metadata() -> None:
    """Asyncpg's direct constraint name identifies only the hash collision."""
    driver_error = _DriverError(
        "duplicate key value violates unique constraint",
        constraint_name="uq_pricing_snapshots_content_hash",
    )
    error = IntegrityError("insert", {}, driver_error)

    assert _is_pricing_snapshot_hash_collision(error), (
        "the declared constraint name must identify asyncpg collisions"
    )


def test_hash_collision_uses_psycopg_diagnostic_metadata() -> None:
    """Psycopg's diagnostic constraint name identifies hash collisions."""
    driver_error = _DriverError(
        "duplicate key value violates unique constraint",
        diagnostic_constraint_name="uq_pricing_snapshots_content_hash",
    )
    error = IntegrityError("insert", {}, driver_error)

    assert _is_pricing_snapshot_hash_collision(error), (
        "the declared constraint name must identify psycopg collisions"
    )


@pytest.mark.parametrize(
    ("message", "expected_classification"),
    [
        (_HASH_CONSTRAINT_ERROR, "collision"),
        (
            "null value in column content_hash violates not-null constraint",
            "unrelated",
        ),
        (
            'duplicate key value violates unique constraint "other_unique_key"',
            "unrelated",
        ),
    ],
)
def test_hash_collision_message_fallback_is_narrow(
    message: str,
    expected_classification: str,
) -> None:
    """Only the exact named PostgreSQL constraint matches the fallback."""
    error = IntegrityError("insert", {}, RuntimeError(message))

    assert _is_pricing_snapshot_hash_collision(error) is (
        expected_classification == "collision"
    ), f"unexpected classification for driver error {message!r}"
