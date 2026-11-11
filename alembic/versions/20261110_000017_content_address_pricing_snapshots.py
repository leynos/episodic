"""Convert pricing snapshots to schema version 1 content addressing.

Revision ID: 20261110_000017
Revises: 20261031_000016
Create Date: 2026-11-10

The converter and canonicalizer are frozen inline copies of the application
logic. A migration must keep producing the same bytes after the application
code moves on, so it may not import from ``episodic``.
"""

import collections.abc as cabc
import datetime as dt
import hashlib
import json
import math
import re
import typing as typ

import sqlalchemy as sa
from alembic.util import CommandError
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20261110_000017"
down_revision: str | None = "20261031_000016"
branch_labels: str | None = None
depends_on: str | None = None

_RATE_SCALE = 1_000_000
_MAX_JSON_INT = 2**53 - 1
_LEGACY_METRIC_UNITS: typ.Final = {
    "input_tokens": "token",
    "output_tokens": "token",
    "cached_input_tokens": "token",
    "cache_write_tokens": "token",
    "reasoning_tokens": "token",
    "audio_input_tokens": "token",
    "audio_output_tokens": "token",
}
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_REQUIRED_TEXT_FIELDS = ("provider_name", "model", "operation")
_SOURCE_KINDS = frozenset({"provider_rate_card", "sla4oai_plan"})
_CURRENCY_CODE = re.compile(r"^[A-Z]{3}$")
_EMPTY_TABLE_GUARD = (
    "DO $$ BEGIN IF EXISTS (SELECT 1 FROM pricing_snapshots) THEN RAISE EXCEPTION "
    "'pricing_snapshots must be empty to run this migration'; END IF; END $$;"
)


def _instant(value: dt.datetime) -> str:
    """Format an instant exactly as the application canonicalizer does."""
    return value.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _reject(snapshot_id: object, detail: str) -> typ.NoReturn:
    """Raise a conversion error naming the offending snapshot."""
    msg = f"pricing snapshot {snapshot_id}: {detail}"
    raise CommandError(msg)


def _row_instant(value: object, snapshot_id: object) -> dt.datetime:
    """Reject a legacy row whose instant is not a datetime."""
    if not isinstance(value, dt.datetime):
        _reject(snapshot_id, "instant is not a datetime")
    return value


def _is_legacy_amount(amount: object) -> typ.TypeGuard[int]:
    """Return whether a legacy rate is a non-negative, non-boolean integer."""
    return isinstance(amount, int) and not isinstance(amount, bool) and amount >= 0


def _convert_rates(
    legacy_rates: cabc.Mapping[str, object],
    snapshot_id: object,
) -> dict[str, dict[str, object]]:
    """Convert per-million integer rates to exact lowest-term fractions."""
    converted: dict[str, dict[str, object]] = {}
    for metric, amount in legacy_rates.items():
        if metric not in _LEGACY_METRIC_UNITS:
            _reject(snapshot_id, f"legacy metric {metric!r} has no declared unit")
        if not _is_legacy_amount(amount):
            _reject(snapshot_id, f"rate for {metric!r} must be a non-negative integer")
        divisor = math.gcd(amount, _RATE_SCALE)
        amount_minor = amount // divisor
        if amount_minor > _MAX_JSON_INT:
            _reject(
                snapshot_id,
                f"rate for {metric!r} exceeds the canonical JSON integer limit "
                f"{_MAX_JSON_INT}",
            )
        converted[metric] = {
            "amount_minor": amount_minor,
            "per_units": _RATE_SCALE // divisor,
            "unit": _LEGACY_METRIC_UNITS[metric],
        }
    return converted


def _convert_metadata(
    legacy_metadata: cabc.Mapping[str, object],
    snapshot_id: object,
) -> dict[str, str]:
    """Validate legacy source metadata against the v1 identifier rule."""
    converted: dict[str, str] = {}
    for key, value in legacy_metadata.items():
        if not isinstance(key, str) or not _IDENTIFIER.fullmatch(key):
            _reject(snapshot_id, f"source metadata key {key!r} is not an identifier")
        if not isinstance(value, str):
            _reject(snapshot_id, f"source metadata value for {key!r} must be a string")
        converted[key] = value
    return converted


def _canonical_document(
    row: cabc.Mapping[str, object],
    rates: dict[str, dict[str, object]],
    metadata: dict[str, str],
) -> dict[str, object]:
    """Build the schema-version-1 canonical document for one legacy row."""
    effective_from = row["effective_from"]
    return {
        "currency": row["currency"],
        "effective_from": (
            None
            if effective_from is None
            else _instant(_row_instant(effective_from, row["id"]))
        ),
        "model": row["model"],
        "operation": row["operation"],
        "provider_name": row["provider_name"],
        "rates": rates,
        "retrieved_at": _instant(_row_instant(row["retrieved_at"], row["id"])),
        "schema_version": 1,
        "service_kind": "llm",
        "source_document": None,
        "source_kind": row["source_kind"],
        "source_metadata": metadata,
    }


def _content_hash(document: dict[str, object]) -> str:
    """Hash a canonical document exactly as the application does."""
    payload = json.dumps(
        document,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def _is_currency_code(value: object) -> bool:
    """Return whether a value is three uppercase ASCII letters."""
    # The domain pattern is repeated rather than imported because a migration
    # must keep converting rows the way it always did, even when the domain
    # validator later changes.
    return isinstance(value, str) and _CURRENCY_CODE.fullmatch(value) is not None


def _require_json_objects(
    row: cabc.Mapping[str, object],
    snapshot_id: object,
) -> None:
    """Reject legacy JSONB columns that do not hold objects."""
    # The columns are JSONB, so a row can hold an array or a scalar. Converting
    # one would fail on ``.items()`` without naming the row, so the shape is
    # checked where the snapshot identifier is in hand.
    for field in ("rates_minor_per_metric", "source_metadata"):
        if not isinstance(row[field], cabc.Mapping):
            _reject(snapshot_id, f"{field} must be a JSON object")


def _validate_row(row: cabc.Mapping[str, object], snapshot_id: object) -> None:
    """Reject a legacy row that cannot become a valid version 1 snapshot.

    A row that escaped these checks would migrate into a snapshot that ``get``
    can never rebuild, so the migration fails loudly instead.
    """
    for field in _REQUIRED_TEXT_FIELDS:
        value = row[field]
        if not isinstance(value, str) or not value.strip():
            _reject(snapshot_id, f"{field} must be a non-blank string")
    if not _is_currency_code(row["currency"]):
        _reject(snapshot_id, "currency must be a three-letter uppercase ASCII code")
    source_kind = row["source_kind"]
    if source_kind not in _SOURCE_KINDS:
        _reject(snapshot_id, f"unknown source kind {source_kind!r}")
    if source_kind == "sla4oai_plan":
        _reject(snapshot_id, "a legacy sla4oai_plan row carries no source document")
    _require_json_objects(row, snapshot_id)
    if not row["rates_minor_per_metric"]:
        _reject(snapshot_id, "a snapshot must price at least one metric")


def _converted_row(
    row: cabc.Mapping[str, object],
) -> tuple[dict[str, dict[str, object]], dict[str, str], str]:
    """Convert one legacy row and return its rates, metadata, and hash."""
    snapshot_id = row["id"]
    _validate_row(row, snapshot_id)
    rates = _convert_rates(
        typ.cast("cabc.Mapping[str, object]", row["rates_minor_per_metric"]),
        snapshot_id,
    )
    metadata = _convert_metadata(
        typ.cast("cabc.Mapping[str, object]", row["source_metadata"]),
        snapshot_id,
    )
    document = _canonical_document(row, rates, metadata)
    return rates, metadata, _content_hash(document)


def _add_new_columns() -> None:
    """Add the schema-version-1 columns as nullable."""
    op.add_column("pricing_snapshots", sa.Column("schema_version", sa.Integer))
    op.add_column("pricing_snapshots", sa.Column("service_kind", sa.Text))
    op.add_column("pricing_snapshots", sa.Column("rates", postgresql.JSONB))
    for column in ("source_document_media_type", "source_document_content"):
        op.add_column("pricing_snapshots", sa.Column(column, sa.Text))
    op.add_column(
        "pricing_snapshots",
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )


def _tighten_new_columns() -> None:
    """Make the required new columns non-null and add their checks."""
    for column in ("schema_version", "service_kind", "rates", "recorded_at"):
        op.alter_column("pricing_snapshots", column, nullable=False)
    checks = {
        "ck_pricing_snapshots_schema_version": "schema_version = 1",
        "ck_pricing_snapshots_service_kind": (
            "service_kind IN ('llm', 'tts', 'helper_service')"
        ),
        "ck_pricing_snapshots_source_kind": (
            "source_kind IN ('provider_rate_card', 'sla4oai_plan')"
        ),
        "ck_pricing_snapshots_source_document_pair": (
            "(source_document_media_type IS NULL) = (source_document_content IS NULL)"
        ),
        "ck_pricing_snapshots_source_document_required": (
            "source_kind <> 'sla4oai_plan' OR source_document_content IS NOT NULL"
        ),
    }
    for name, condition in checks.items():
        op.create_check_constraint(name, "pricing_snapshots", condition)


def _drop_legacy_columns() -> None:
    """Remove the columns the v1 representation replaces."""
    op.drop_column("pricing_snapshots", "billing_period_key")
    op.drop_column("pricing_snapshots", "rates_minor_per_metric")


def _legacy_rows(connection: sa.Connection) -> list[dict[str, object]]:
    """Read every legacy row before conversion, oldest first."""
    # A stable order makes the first row for a content hash the survivor when
    # equivalent rows are merged, so the choice does not depend on heap order.
    result = connection.execute(
        sa.text(
            "SELECT id, provider_name, model, operation, source_kind, currency, "
            "rates_minor_per_metric, source_metadata, retrieved_at, "
            "effective_from FROM pricing_snapshots "
            "ORDER BY retrieved_at, id"
        )
    )
    return [dict(row._mapping) for row in result]


def _merge_equivalent_row(
    connection: sa.Connection,
    *,
    duplicate: object,
    survivor: object,
) -> None:
    """Point every reference at the survivor, then delete the duplicate."""
    # Legacy rows that differed only by billing period collapse into one
    # version once the period leaves the snapshot. Both rows are valid and may
    # be pinned, so the references move rather than the upgrade aborting.
    params = {"duplicate": duplicate, "survivor": survivor}
    for statement in (
        sa.text(
            "UPDATE cost_ledger_entries SET pricing_snapshot_id = :survivor "
            "WHERE pricing_snapshot_id = :duplicate"
        ),
        sa.text(
            "UPDATE run_pricing_pins SET pricing_snapshot_id = :survivor "
            "WHERE pricing_snapshot_id = :duplicate"
        ),
    ):
        connection.execute(statement, params)
    connection.execute(
        sa.text("DELETE FROM pricing_snapshots WHERE id = :duplicate"),
        {"duplicate": duplicate},
    )


def _write_converted_rows(
    connection: sa.Connection,
    rows: cabc.Sequence[dict[str, object]],
) -> None:
    """Convert and write every legacy row, merging equivalent content."""
    survivors: dict[str, object] = {}
    for row in rows:
        rates, metadata, content_hash = _converted_row(row)
        survivor = survivors.get(content_hash)
        if survivor is not None:
            _merge_equivalent_row(connection, duplicate=row["id"], survivor=survivor)
            continue
        survivors[content_hash] = row["id"]
        connection.execute(
            sa.text(
                "UPDATE pricing_snapshots SET schema_version = 1, "
                "service_kind = 'llm', rates = CAST(:rates AS jsonb), "
                "source_metadata = CAST(:metadata AS jsonb), "
                "content_hash = :content_hash WHERE id = :id"
            ),
            {
                "rates": json.dumps(rates, sort_keys=True),
                "metadata": json.dumps(metadata, sort_keys=True),
                "content_hash": content_hash,
                "id": row["id"],
            },
        )


def upgrade() -> None:
    """Convert legacy snapshots to schema version 1 content addressing."""
    context = op.get_context()
    if context.as_sql:
        op.execute(_EMPTY_TABLE_GUARD)
        _add_new_columns()
        _tighten_new_columns()
        _drop_legacy_columns()
        return
    connection = op.get_bind()
    connection.execute(sa.text("LOCK TABLE pricing_snapshots IN ACCESS EXCLUSIVE MODE"))
    _add_new_columns()
    _write_converted_rows(connection, _legacy_rows(connection))
    _tighten_new_columns()
    _drop_legacy_columns()


def downgrade() -> None:
    """Refuse to downgrade a populated table, then reverse the DDL."""
    context = op.get_context()
    if context.as_sql:
        op.execute(_EMPTY_TABLE_GUARD)
    else:
        connection = op.get_bind()
        connection.execute(
            sa.text("LOCK TABLE pricing_snapshots IN ACCESS EXCLUSIVE MODE")
        )
        stored = connection.scalar(sa.text("SELECT count(*) FROM pricing_snapshots"))
        if stored:
            msg = (
                "pricing_snapshots must be empty to downgrade "
                "20261110_000017; converted rows cannot be mapped back"
            )
            raise CommandError(msg)
    for name in (
        "ck_pricing_snapshots_source_document_required",
        "ck_pricing_snapshots_source_document_pair",
        "ck_pricing_snapshots_source_kind",
        "ck_pricing_snapshots_service_kind",
        "ck_pricing_snapshots_schema_version",
    ):
        op.drop_constraint(name, "pricing_snapshots", type_="check")
    op.add_column(
        "pricing_snapshots",
        sa.Column("billing_period_key", sa.Text),
    )
    op.add_column(
        "pricing_snapshots",
        sa.Column("rates_minor_per_metric", postgresql.JSONB),
    )
    op.alter_column("pricing_snapshots", "billing_period_key", nullable=False)
    op.alter_column("pricing_snapshots", "rates_minor_per_metric", nullable=False)
    for column in (
        "recorded_at",
        "source_document_content",
        "source_document_media_type",
        "rates",
        "service_kind",
        "schema_version",
    ):
        op.drop_column("pricing_snapshots", column)
