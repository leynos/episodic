"""Online and offline coverage for the content-address migration."""

import datetime as dt
import hashlib
import io
import json
import logging
import typing as typ
import uuid

import pytest
import sqlalchemy as sa
from alembic.util import CommandError

from alembic import command
from episodic.canonical.storage.alembic_helpers import alembic_config
from episodic.cost import CurrencyCode, PricingSourceKind
from episodic.cost.pricing_snapshot import (
    PricedService,
    PricingSnapshot,
    SourceDocument,
)
from episodic.cost.pricing_snapshot_hash import pricing_snapshot_content_hash
from tests.fixtures.legacy_pricing_snapshots import (
    LEGACY_REVISION,
    NEW_REVISION,
    assert_upgrade_fails,
    columns,
    downgrade,
    legacy_row,
    rows,
    seed_legacy_rows,
    upgrade,
    upgrade_is_rejected,
)
from tests.fixtures.migration_doubles import RecordMessages, colliding_sha256

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine
    from syrupy.assertion import SnapshotAssertion


@pytest.mark.asyncio
async def test_upgrade_converts_legacy_rows(
    migrated_engine: AsyncEngine,
    snapshot: SnapshotAssertion,
) -> None:
    """Legacy rows become v1 rows with exact rates and a content hash."""
    async with migrated_engine.begin() as connection:
        await seed_legacy_rows(
            connection,
            [legacy_row(uuid.UUID(int=11))],
        )
        await upgrade(connection)
        current_columns = await columns(connection)
        converted_rows = await rows(connection)

    assert "billing_period_key" not in current_columns, (
        "the legacy billing period column must be dropped"
    )
    assert "rates_minor_per_metric" not in current_columns, (
        "the legacy integer rate column must be dropped"
    )
    assert {"schema_version", "service_kind", "rates", "recorded_at"} <= (
        current_columns
    ), "the v1 columns must all be added"
    assert len(converted_rows) == 1, "the legacy row must survive the conversion"
    converted = converted_rows[0]
    assert converted["schema_version"] == 1, "converted rows are schema version 1"
    assert converted["service_kind"] == "llm", "legacy rows convert as LLM pricing"
    assert converted["source_kind"] == "provider_rate_card", (
        "the legacy source kind must be preserved"
    )
    assert converted["rates"] == snapshot, (
        "legacy per-million rates must convert to exact lowest-term fractions"
    )
    assert converted["retrieved_at"] == dt.datetime(2026, 6, 1, tzinfo=dt.UTC), (
        "the retrieved instant must round-trip unchanged"
    )
    assert converted["effective_from"] == dt.datetime(2026, 6, 1, tzinfo=dt.UTC), (
        "the effective instant must round-trip unchanged"
    )
    assert str(converted["content_hash"]).startswith("sha256:"), (
        "the conversion must store a content hash"
    )
    assert converted["recorded_at"] is not None, (
        "the conversion must stamp a recording instant"
    )


async def _seed_duplicate_rows(connection: AsyncConnection) -> None:
    """Seed two legacy rows that differ only by billing period."""
    await seed_legacy_rows(
        connection,
        [
            legacy_row(
                _SURVIVOR,
                billing_period_key="2026-05",
                content_hash="legacy-may",
            ),
            legacy_row(
                _DUPLICATE,
                billing_period_key="2026-06",
                content_hash="legacy-june",
            ),
        ],
    )


_SURVIVOR = uuid.UUID(int=21)
_DUPLICATE = uuid.UUID(int=22)
_LEDGER_SQL = sa.text(
    "INSERT INTO cost_ledger_entries (id, idempotency_key, scope, provider_type, "
    "provider_name, operation, pricing_snapshot_id, usage, usage_source, "
    "usage_complete, computed_cost_minor, currency, pricing_model, retry_attempt, "
    "billing_period_key, workflow_run_id, recorded_at) VALUES "
    "('00000000-0000-0000-0000-0000000000a1', 'ledger-1', 'run', 'llm', 'openai', "
    "'chat_completions', :snapshot, '{}'::jsonb, 'provider_reported', true, 0, "
    "'USD', 'pinned_snapshot', 0, '2026-06', 'run-1', now())"
)


@pytest.mark.asyncio
async def test_upgrade_merges_rows_that_differ_only_by_billing_period(
    migrated_engine: AsyncEngine,
) -> None:
    """Equivalent legacy rows collapse into one version and keep their pins."""
    # The legacy rows differ only in billing period and stored hash, which keeps
    # the seed within the pre-existing uniqueness constraint; the conversion
    # still produces one shared identity.
    async with migrated_engine.begin() as connection:
        await _seed_duplicate_rows(connection)
        await connection.execute(
            sa.text(
                "INSERT INTO run_pricing_pins (workflow_run_id, provider_name, "
                "model, operation, billing_period_key, pricing_snapshot_id) "
                "VALUES ('run-1', 'openai', 'gpt-4o-mini', 'chat_completions', "
                "'2026-06', :snapshot)"
            ),
            {"snapshot": _DUPLICATE},
        )
        await connection.execute(_LEDGER_SQL, {"snapshot": _DUPLICATE})
        await upgrade(connection)
        converted_rows = await rows(connection)
        pinned = (
            await connection.execute(
                sa.text("SELECT pricing_snapshot_id FROM run_pricing_pins")
            )
        ).scalar_one()
        ledgered = (
            await connection.execute(
                sa.text("SELECT pricing_snapshot_id FROM cost_ledger_entries")
            )
        ).scalar_one()

    assert [row["id"] for row in converted_rows] == [_SURVIVOR], (
        "equivalent rows must merge into the earliest snapshot"
    )
    assert pinned == _SURVIVOR, "a pin on the duplicate must follow the survivor"
    assert ledgered == _SURVIVOR, "a ledger entry on the duplicate must follow it"


@pytest.mark.asyncio
async def test_upgrade_reports_its_conversion_totals(
    migrated_engine: AsyncEngine,
) -> None:
    """An operator watching the upgrade learns how much work it committed."""
    # Handlers cannot see the line, but filters survive env.py's fileConfig.
    recorder = RecordMessages()
    logger = logging.getLogger("alembic.runtime.migration")
    logger.addFilter(recorder)
    try:
        async with migrated_engine.begin() as connection:
            await _seed_duplicate_rows(connection)
            await upgrade(connection)
    finally:
        logger.removeFilter(recorder)

    expected = "pricing snapshots converted to schema version 1: converted=1 merged=1"
    assert expected in recorder.messages, (
        f"the upgrade must report its conversion totals, got {recorder.messages!r}"
    )


@pytest.mark.asyncio
async def test_upgrade_preserves_a_legacy_sla4oai_row(
    migrated_engine: AsyncEngine,
) -> None:
    """A legacy plan row keeps its kind and gains a faithful JSON document."""
    identifier = uuid.UUID(int=51)
    async with migrated_engine.begin() as connection:
        await seed_legacy_rows(
            connection,
            [
                legacy_row(
                    identifier,
                    source_kind="sla4oai_plan",
                    rates_minor_per_metric={},
                )
            ],
        )
        await upgrade(connection)
        converted_rows = await rows(connection)

    assert len(converted_rows) == 1, "a legacy plan row must survive the conversion"
    converted = converted_rows[0]
    assert converted["source_kind"] == "sla4oai_plan", (
        "the plan kind must not be rewritten as a provider rate card"
    )
    assert converted["rates"] == {}, "a plan may carry no normalized rates"
    assert converted["source_document_media_type"] == "application/json", (
        "the reconstructed document must declare its media type"
    )
    document = json.loads(str(converted["source_document_content"]))
    assert document["source_kind"] == "sla4oai_plan", (
        "the document must preserve the row's source kind"
    )
    assert document["provider_name"] == "openai", (
        "the document must preserve the row's subject"
    )
    expected = PricingSnapshot(
        service_kind=PricedService.LLM,
        provider_name="openai",
        model="gpt-4o-mini",
        operation="chat_completions",
        source_kind=PricingSourceKind.SLA4OAI_PLAN,
        currency=CurrencyCode("USD"),
        rates={},
        source_metadata={"source": "migration-test"},
        retrieved_at=dt.datetime(2026, 6, 1, tzinfo=dt.UTC),
        effective_from=dt.datetime(2026, 6, 1, tzinfo=dt.UTC),
        source_document=SourceDocument(
            media_type="application/json",
            content=str(converted["source_document_content"]),
        ),
    )
    assert converted["content_hash"] == pricing_snapshot_content_hash(expected), (
        "the store must recompute the migrated identity without an integrity error"
    )


@pytest.mark.asyncio
async def test_upgrade_rolls_back_a_content_hash_collision(
    migrated_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A collision aborts inside the upgrade and rewrites no stored row."""
    survivor = uuid.UUID(int=91)
    duplicate = uuid.UUID(int=92)
    async with migrated_engine.begin() as connection:
        await seed_legacy_rows(
            connection,
            [
                legacy_row(survivor, provider_name="openai", content_hash="legacy-a"),
                legacy_row(
                    duplicate, provider_name="anthropic", content_hash="legacy-b"
                ),
            ],
        )
        # Two different documents can only share an identity if the digest
        # repeats, so the hash function is forced rather than an input found.
        monkeypatch.setattr(hashlib, "sha256", colliding_sha256)
        await upgrade_is_rejected(connection, "content differs")
        stored = {str(row["id"]): row for row in await rows(connection)}

    assert set(stored) == {str(survivor), str(duplicate)}, (
        "the aborted upgrade must keep both legacy rows"
    )
    assert {row["content_hash"] for row in stored.values()} == {
        "legacy-a",
        "legacy-b",
    }, "the survivor's rewrite must be rolled back, not committed"
    assert all(row["rates_minor_per_metric"] for row in stored.values()), (
        "the legacy rate column must survive the aborted upgrade"
    )


@pytest.mark.asyncio
async def test_upgrade_rejects_an_unknown_legacy_metric(
    migrated_engine: AsyncEngine,
) -> None:
    """A metric with no declared unit cannot be converted safely."""
    overrides = {"rates_minor_per_metric": {"mystery": 5}}
    await assert_upgrade_fails(migrated_engine, uuid.UUID(int=31), overrides, "mystery")


@pytest.mark.asyncio
async def test_upgrade_rejects_a_non_identifier_metadata_key(
    migrated_engine: AsyncEngine,
) -> None:
    """Canonical source metadata keys must be identifiers."""
    identifier = uuid.UUID(int=41)
    overrides = {"source_metadata": {"Source URL": "x"}}
    await assert_upgrade_fails(migrated_engine, identifier, overrides, str(identifier))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        pytest.param({"provider_name": "  "}, "provider_name", id="blank-provider"),
        pytest.param({"model": ""}, "model", id="blank-model"),
        pytest.param({"operation": ""}, "operation", id="blank-operation"),
        pytest.param({"currency": "US"}, "currency", id="short-currency"),
        pytest.param({"currency": "usd"}, "uppercase", id="lowercase-currency"),
        pytest.param({"currency": "ÉÜÖ"}, "uppercase", id="non-ascii-currency"),
        pytest.param(
            {"rates_minor_per_metric": {"input_tokens": 2**53 + 1}},
            "canonical JSON integer limit",
            id="rate-above-json-integer-limit",
        ),
        pytest.param({"source_kind": "mystery"}, "source kind", id="unknown-source"),
        pytest.param(
            {"rates_minor_per_metric": {}},
            "at least one metric",
            id="empty-rates",
        ),
        pytest.param(
            {"rates_minor_per_metric": ["input_tokens"]},
            "must be a JSON object",
            id="non-object-rates",
        ),
        pytest.param(
            {"source_metadata": ["source_url"]},
            "must be a JSON object",
            id="non-object-metadata",
        ),
    ],
)
async def test_upgrade_rejects_a_row_that_cannot_be_version_one(
    migrated_engine: AsyncEngine,
    overrides: dict[str, object],
    match: str,
) -> None:
    """A row the application would reject must not migrate into a broken snapshot."""
    await assert_upgrade_fails(migrated_engine, uuid.UUID(int=61), overrides, match)


@pytest.mark.asyncio
async def test_downgrade_refuses_when_rows_exist(
    migrated_engine: AsyncEngine,
) -> None:
    """Converted rows cannot be mapped back to the legacy representation."""
    async with migrated_engine.begin() as connection:
        await seed_legacy_rows(connection, [legacy_row(uuid.UUID(int=51))])
        await upgrade(connection)
        with pytest.raises(CommandError, match="empty"):
            await downgrade(connection, LEGACY_REVISION)


def _offline_sql(
    migrate: cabc.Callable[..., None],
    revision_range: str,
) -> str:
    """Render one offline migration command and return the emitted SQL."""
    config = alembic_config("postgresql://offline.example/episodic")
    output = io.StringIO()
    config.output_buffer = output
    migrate(config, revision_range, sql=True)
    return output.getvalue()


def _assert_empty_table_guard(emitted: str, direction: str) -> None:
    """Assert offline SQL carries the guard that refuses a populated table."""
    assert "DO $$" in emitted, f"offline {direction} must emit a guard block"
    assert "RAISE EXCEPTION" in emitted.upper(), (
        "the guard must raise on a populated table"
    )


def test_offline_upgrade_guards_against_existing_rows() -> None:
    """Offline DDL cannot convert rows, so it refuses to run on a populated table."""
    emitted = _offline_sql(command.upgrade, f"{LEGACY_REVISION}:{NEW_REVISION}")

    _assert_empty_table_guard(emitted, "upgrade")
    assert "pricing_snapshots" in emitted, "the guard must name the table it protects"


def test_offline_downgrade_guards_against_existing_rows() -> None:
    """Offline downgrade emits the same emptiness guard."""
    emitted = _offline_sql(command.downgrade, f"{NEW_REVISION}:{LEGACY_REVISION}")

    _assert_empty_table_guard(emitted, "downgrade")
