"""Unit coverage for the content-address migration's row conversion."""

import datetime as dt
import importlib.util
import pathlib
import typing as typ
import uuid

import pytest
from alembic.util import CommandError

if typ.TYPE_CHECKING:
    import collections.abc as cabc
    import types

_MIGRATION = (
    pathlib.Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "20261110_000017_content_address_pricing_snapshots.py"
)
_MAX_SOURCE_DOCUMENT_BYTES = 262_144


def _migration() -> types.ModuleType:
    """Load the migration by path, the way Alembic would."""
    spec = importlib.util.spec_from_file_location(
        "content_address_migration",
        _MIGRATION,
    )
    assert spec is not None, "the migration must be loadable by its path"
    assert spec.loader is not None, "the loaded migration must have a loader"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _converter() -> cabc.Callable[[dict[str, object]], object]:
    """Return the migration's row converter.

    The oversized-document guard cannot be exercised through py-pglite: the
    embedded server closes the connection for parameters above roughly 64 KiB,
    so a legacy row large enough to trip the cap cannot be seeded. Converting
    a row directly proves the guard without a database round trip.

    Returns
    -------
    collections.abc.Callable[[dict[str, object]], object]
        The migration's conversion step for one legacy row.
    """
    return typ.cast(
        "cabc.Callable[[dict[str, object]], object]", _migration()._converted_row
    )


def test_conversion_rejects_an_oversized_plan_document() -> None:
    """A reconstructed plan document above the domain cap must not migrate."""
    row: dict[str, object] = {
        "id": uuid.UUID(int=71),
        "provider_name": "openai",
        "model": "gpt-4o-mini",
        "operation": "chat_completions",
        "source_kind": "sla4oai_plan",
        "currency": "USD",
        "rates_minor_per_metric": {},
        "source_metadata": {"source_url": "x" * _MAX_SOURCE_DOCUMENT_BYTES},
        "retrieved_at": dt.datetime(2026, 6, 1, tzinfo=dt.UTC),
        "effective_from": None,
        "billing_period_key": "2026-06",
    }

    with pytest.raises(CommandError, match="262,144-byte cap"):
        _converter()(row)


@pytest.mark.parametrize("year", [1, 99, 999])
def test_frozen_instant_keeps_a_four_digit_year(year: int) -> None:
    """The migration's instant must pad the year the way the domain does."""
    stored = dt.datetime(year, 1, 1, tzinfo=dt.UTC)
    instant = _migration()._instant(stored, uuid.uuid4())

    assert instant == f"{year:04d}-01-01T00:00:00.000000Z", (
        "a migrated row must hash identically to the application's encoding"
    )


class _RecordingConnection:
    """Stand-in connection that records statements rather than running them."""

    def __init__(self) -> None:
        """Start with no recorded statements."""
        self.statements: list[object] = []

    def execute(self, statement: object, *_: object) -> None:
        """Record one statement."""
        self.statements.append(statement)


def test_shared_hash_with_different_content_aborts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A hash shared by different bytes must abort instead of merging rows."""
    survivor = uuid.UUID(int=81)
    duplicate = uuid.UUID(int=82)
    module = _migration()
    # A hash collision is the only way two different documents reach the same
    # identity, so the converter is stubbed rather than a colliding input found.
    texts = iter(("first document", "second document"))
    monkeypatch.setattr(
        module,
        "_converted_row",
        lambda row: ({}, {}, None, "sha256:shared", next(texts)),
    )
    connection = _RecordingConnection()

    # The migration is loaded as a module, so its write step is reached through
    # module attributes: these are the frozen internals under test.
    with pytest.raises(CommandError, match="content differs") as rejection:
        module._write_converted_rows(
            connection,
            [{"id": survivor}, {"id": duplicate}],
        )

    message = str(rejection.value)
    assert str(survivor) in message, "the collision must name the survivor"
    assert str(duplicate) in message, "the collision must name the duplicate"
    # The survivor's conversion executes before the duplicate is compared, so
    # the table is left partly rewritten unless the caller rolls back. The
    # Alembic transaction boundary test proves that rollback.
    assert len(connection.statements) == 1, (
        "only the survivor may be written before the collision aborts the merge"
    )
    assert "UPDATE pricing_snapshots SET schema_version = 1" in str(
        connection.statements[0]
    ), "the recorded statement must be the survivor's conversion"
