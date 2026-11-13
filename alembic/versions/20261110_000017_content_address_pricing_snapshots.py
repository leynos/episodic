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

_Row = cabc.Mapping[str, object]
_RATE_SCALE = 1_000_000
_MAX_JSON_INT = 2**53 - 1
# The legacy table never stored an SLA4OAI row's plan text, so the upgraded row
# carries the legacy columns as JSON under a media type naming that reconstruction.
_LEGACY_DOCUMENT_MEDIA_TYPE = "application/json"
_MAX_SOURCE_DOCUMENT_BYTES = 262_144  # Mirrors SourceDocument's cap.
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
_CHECK_CONSTRAINTS: typ.Final = (
    ("ck_pricing_snapshots_schema_version", "schema_version = 1"),
    (
        "ck_pricing_snapshots_service_kind",
        "service_kind IN ('llm', 'tts', 'helper_service')",
    ),
    (
        "ck_pricing_snapshots_source_kind",
        "source_kind IN ('provider_rate_card', 'sla4oai_plan')",
    ),
    (
        "ck_pricing_snapshots_source_document_pair",
        "(source_document_media_type IS NULL) = (source_document_content IS NULL)",
    ),
    (
        "ck_pricing_snapshots_source_document_required",
        "source_kind <> 'sla4oai_plan' OR source_document_content IS NOT NULL",
    ),
)
_EMPTY_TABLE_GUARD = (
    "DO $$ BEGIN IF EXISTS (SELECT 1 FROM pricing_snapshots) THEN RAISE EXCEPTION "
    "'pricing_snapshots must be empty to run this migration'; END IF; END $$;"
)


def _instant(value: dt.datetime) -> str:
    """Format an instant exactly as the application canonicalizer does."""
    # ``strftime("%Y")`` leaves years below 1000 unpadded, so the year is
    # formatted separately and the remaining fields keep their fixed widths.
    utc = value.astimezone(dt.UTC)
    return f"{utc.year:04d}-{utc:%m-%dT%H:%M:%S.%f}Z"


def _canonical_json(document: dict[str, object]) -> str:
    """Serialize a document exactly as the application canonicalizer does."""
    return json.dumps(
        document,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _reject(snapshot_id: object, detail: str) -> typ.NoReturn:
    """Raise a conversion error naming the offending snapshot."""
    msg = f"pricing snapshot {snapshot_id}: {detail}"
    raise CommandError(msg)


def _row_instant(value: object, snapshot_id: object) -> dt.datetime:
    """Reject a legacy row whose instant is not a datetime."""
    if not isinstance(value, dt.datetime):
        _reject(snapshot_id, "instant is not a datetime")
    return value


def _convert_rates(
    legacy_rates: cabc.Mapping[str, object],
    snapshot_id: object,
) -> dict[str, dict[str, object]]:
    """Convert per-million integer rates to exact lowest-term fractions."""
    converted: dict[str, dict[str, object]] = {}
    for metric, amount in legacy_rates.items():
        if metric not in _LEGACY_METRIC_UNITS:
            _reject(snapshot_id, f"legacy metric {metric!r} has no declared unit")
        if isinstance(amount, bool) or not isinstance(amount, int):
            _reject(snapshot_id, f"rate for {metric!r} must be an integer")
        if amount < 0:
            _reject(snapshot_id, f"rate for {metric!r} must be non-negative")
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


def _validate_text_fields(row: _Row, snapshot_id: object) -> None:
    """Reject a blank provider, model, or operation."""
    for field in _REQUIRED_TEXT_FIELDS:
        value = row[field]
        if not isinstance(value, str) or not value.strip():
            _reject(snapshot_id, f"{field} must be a non-blank string")


def _validate_currency_and_source_kind(row: _Row, snapshot_id: object) -> None:
    """Reject a currency or source kind the version 1 schema does not define."""
    # The domain pattern is repeated rather than imported because a migration
    # must keep converting rows the way it always did, even when the domain
    # validator later changes.
    currency = row["currency"]
    if not isinstance(currency, str) or not _CURRENCY_CODE.fullmatch(currency):
        _reject(snapshot_id, "currency must be a three-letter uppercase ASCII code")
    source_kind = row["source_kind"]
    if source_kind not in _SOURCE_KINDS:
        _reject(snapshot_id, f"unknown source kind {source_kind!r}")


def _validate_json_columns(row: _Row, snapshot_id: object) -> None:
    """Reject JSON columns that cannot hold the version 1 shapes."""
    # A JSONB column may hold an array or scalar, which would fail on .items().
    for field in ("rates_minor_per_metric", "source_metadata"):
        if not isinstance(row[field], cabc.Mapping):
            _reject(snapshot_id, f"{field} must be a JSON object")
    if row["source_kind"] == "provider_rate_card" and not row["rates_minor_per_metric"]:
        _reject(snapshot_id, "a rate card snapshot must price at least one metric")


def _validate_row(row: _Row, snapshot_id: object) -> None:
    """Reject a legacy row that cannot become a valid version 1 snapshot."""
    _validate_text_fields(row, snapshot_id)
    _validate_currency_and_source_kind(row, snapshot_id)
    _validate_json_columns(row, snapshot_id)


def _converted_row(
    row: _Row,
) -> tuple[
    dict[str, dict[str, object]], dict[str, str], dict[str, str] | None, str, str
]:
    """Convert one legacy row and return its rates, metadata, document, identity."""
    snapshot_id = row["id"]
    _validate_row(row, snapshot_id)
    raw_rates = typ.cast("cabc.Mapping[str, object]", row["rates_minor_per_metric"])
    raw_metadata = typ.cast("cabc.Mapping[str, object]", row["source_metadata"])
    rates = _convert_rates(raw_rates, snapshot_id)
    metadata = _convert_metadata(raw_metadata, snapshot_id)
    document = _canonical_document(row, rates, metadata)
    source_document = None
    if row["source_kind"] == "sla4oai_plan":
        content = _canonical_json(document)
        if len(content.encode("utf-8")) > _MAX_SOURCE_DOCUMENT_BYTES:
            _reject(snapshot_id, "source document exceeds the 262,144-byte cap")
        source_document = {
            "media_type": _LEGACY_DOCUMENT_MEDIA_TYPE,
            "content": content,
        }
        # Identity hashes the digest, as the application encoder does.
        document["source_document"] = {
            "media_type": _LEGACY_DOCUMENT_MEDIA_TYPE,
            "sha256": f"sha256:{hashlib.sha256(content.encode('utf-8')).hexdigest()}",
        }
    canonical_text = _canonical_json(document)
    digest = hashlib.sha256(canonical_text.encode("utf-8")).hexdigest()
    return rates, metadata, source_document, f"sha256:{digest}", canonical_text


def _add_new_columns() -> None:
    """Add the schema-version-1 columns as nullable."""
    for column, type_ in (
        ("schema_version", sa.Integer()),
        ("service_kind", sa.Text()),
        ("rates", postgresql.JSONB()),
        ("source_document_media_type", sa.Text()),
        ("source_document_content", sa.Text()),
    ):
        op.add_column("pricing_snapshots", sa.Column(column, type_))
    recorded_at = sa.Column(
        "recorded_at", sa.DateTime(timezone=True), server_default=sa.func.now()
    )
    op.add_column("pricing_snapshots", recorded_at)


def _tighten_new_columns() -> None:
    """Make the required new columns non-null and add their checks."""
    for column in ("schema_version", "service_kind", "rates", "recorded_at"):
        op.alter_column("pricing_snapshots", column, nullable=False)
    for name, condition in _CHECK_CONSTRAINTS:
        op.create_check_constraint(name, "pricing_snapshots", condition)


def _drop_legacy_columns() -> None:
    """Remove the columns the v1 representation replaces."""
    op.drop_column("pricing_snapshots", "billing_period_key")
    op.drop_column("pricing_snapshots", "rates_minor_per_metric")


def _legacy_rows(connection: sa.Connection) -> list[dict[str, object]]:
    """Read every legacy row, oldest first so the earliest survives a merge."""
    query = sa.text(
        "SELECT id, provider_name, model, operation, source_kind, currency, "
        "rates_minor_per_metric, source_metadata, retrieved_at, "
        "effective_from, billing_period_key FROM pricing_snapshots "
        "ORDER BY retrieved_at, id"
    )
    return [dict(row._mapping) for row in connection.execute(query)]


def _merge_equivalent_row(
    connection: sa.Connection,
    *,
    duplicate: object,
    survivor: object,
) -> None:
    """Point every reference at the survivor, then delete the duplicate."""
    # Rows differing only by billing period collapse; references move, not abort.
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
        connection.execute(statement, {"duplicate": duplicate, "survivor": survivor})
    connection.execute(
        sa.text("DELETE FROM pricing_snapshots WHERE id = :duplicate"),
        {"duplicate": duplicate},
    )


def _write_converted_rows(connection: sa.Connection, rows: cabc.Sequence[_Row]) -> None:
    """Convert and write every legacy row, merging byte-identical content."""
    # A shared hash alone is not proof of equal content, so the canonical text
    # is compared before two rows collapse into one survivor.
    survivors: dict[str, tuple[object, str]] = {}
    for row in rows:
        rates, metadata, source_document, content_hash, text = _converted_row(row)
        first = survivors.get(content_hash)
        if first is not None:
            if first[1] != text:
                _reject(row["id"], f"collides with {first[0]}: content differs")
            _merge_equivalent_row(connection, duplicate=row["id"], survivor=first[0])
            continue
        survivors[content_hash] = (row["id"], text)
        document = source_document or {}
        connection.execute(
            sa.text(
                "UPDATE pricing_snapshots SET schema_version = 1, "
                "service_kind = 'llm', rates = CAST(:rates AS jsonb), "
                "source_metadata = CAST(:metadata AS jsonb), "
                "source_document_media_type = :media_type, "
                "source_document_content = :content, "
                "content_hash = :content_hash WHERE id = :id"
            ),
            {
                "rates": json.dumps(rates, sort_keys=True),
                "metadata": json.dumps(metadata, sort_keys=True),
                "media_type": document.get("media_type"),
                "content": document.get("content"),
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
    for name, _ in _CHECK_CONSTRAINTS:
        op.drop_constraint(name, "pricing_snapshots", type_="check")
    for column, type_ in (
        ("billing_period_key", sa.Text()),
        ("rates_minor_per_metric", postgresql.JSONB()),
    ):
        op.add_column("pricing_snapshots", sa.Column(column, type_))
        op.alter_column("pricing_snapshots", column, nullable=False)
    for column in (
        "recorded_at",
        "source_document_content",
        "source_document_media_type",
        "rates",
        "service_kind",
        "schema_version",
    ):
        op.drop_column("pricing_snapshots", column)
