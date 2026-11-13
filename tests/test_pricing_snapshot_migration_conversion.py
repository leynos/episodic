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

_MIGRATION = (
    pathlib.Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "20261110_000017_content_address_pricing_snapshots.py"
)
_MAX_SOURCE_DOCUMENT_BYTES = 262_144


def _converter() -> cabc.Callable[[dict[str, object]], object]:
    """Load the migration by path and return its row converter.

    The oversized-document guard cannot be exercised through py-pglite: the
    embedded server closes the connection for parameters above roughly 64 KiB,
    so a legacy row large enough to trip the cap cannot be seeded. Converting
    a row directly proves the guard without a database round trip.

    Returns
    -------
    collections.abc.Callable[[dict[str, object]], object]
        The migration's conversion step for one legacy row.
    """
    spec = importlib.util.spec_from_file_location(
        "content_address_migration",
        _MIGRATION,
    )
    assert spec is not None, "the migration must be loadable by its path"
    assert spec.loader is not None, "the loaded migration must have a loader"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return typ.cast(
        "cabc.Callable[[dict[str, object]], object]",
        module._converted_row,
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
