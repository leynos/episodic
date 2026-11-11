"""Convert pricing snapshots to schema version 1 content addressing.

Revision ID: 20261110_000017
Revises: 20261031_000016
Create Date: 2026-11-10

The converter and canonicalizer are frozen inline copies of the application
logic. A migration must keep producing the same bytes after the application
code moves on, so it may not import from ``episodic``.
"""

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

if typ.TYPE_CHECKING:
    import collections.abc as cabc

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
_CURRENCY_LENGTH = 3
_EMPTY_TABLE_GUARD = """
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pricing_snapshots) THEN
        RAISE EXCEPTION
            'pricing_snapshots must be empty to run this migration';
    END IF;
END
$$;
"""


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
            _reject(
                snapshot_id,
                f"source metadata value for {key!r} must be a string",
            )
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
    """Return whether a value is a three-letter uppercase currency code."""
    text = value if isinstance(value, str) else ""
    return len(text) == _CURRENCY_LENGTH and text.isalpha() and text.isupper()


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
        _reject(snapshot_id, "currency must be a three-letter uppercase code")
    source_kind = row["source_kind"]
    if source_kind not in _SOURCE_KINDS:
        _reject(snapshot_id, f"unknown source kind {source_kind!r}")
    if source_kind == "sla4oai_plan":
        _reject(
            snapshot_id,
            "a legacy sla4oai_plan row carries no source document",
        )
    if not row["rates_minor_per_metric"]:
        _reject(
            snapshot_id,
            "a provider_rate_card snapshot must price at least one metric",
        )


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
    op.add_column(
        "pricing_snapshots",
        sa.Column("source_document_media_type", sa.Text),
    )
    op.add_column(
        "pricing_snapshots",
        sa.Column("source_document_content", sa.Text),
    )
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
    op.create_check_constraint(
        "ck_pricing_snapshots_schema_version",
        "pricing_snapshots",
        "schema_version = 1",
    )
    op.create_check_constraint(
        "ck_pricing_snapshots_service_kind",
        "pricing_snapshots",
        "service_kind IN ('llm', 'tts', 'helper_service')",
    )
    op.create_check_constraint(
        "ck_pricing_snapshots_source_kind",
        "pricing_snapshots",
        "source_kind IN ('provider_rate_card', 'sla4oai_plan')",
    )
    op.create_check_constraint(
        "ck_pricing_snapshots_source_document_pair",
        "pricing_snapshots",
        "(source_document_media_type IS NULL) = (source_document_content IS NULL)",
    )
    op.create_check_constraint(
        "ck_pricing_snapshots_source_document_required",
        "pricing_snapshots",
        "source_kind <> 'sla4oai_plan' OR source_document_content IS NOT NULL",
    )


def _drop_legacy_columns() -> None:
    """Remove the columns the v1 representation replaces."""
    op.drop_column("pricing_snapshots", "billing_period_key")
    op.drop_column("pricing_snapshots", "rates_minor_per_metric")


def _legacy_rows(connection: sa.Connection) -> list[dict[str, object]]:
    """Read every legacy row before conversion."""
    result = connection.execute(
        sa.text(
            "SELECT id, provider_name, model, operation, source_kind, currency, "
            "rates_minor_per_metric, source_metadata, retrieved_at, "
            "effective_from FROM pricing_snapshots"
        )
    )
    return [dict(row._mapping) for row in result]


def _write_converted_rows(
    connection: sa.Connection,
    rows: cabc.Sequence[dict[str, object]],
) -> None:
    """Convert and write every legacy row, rejecting hash collisions."""
    seen: dict[str, object] = {}
    for row in rows:
        rates, metadata, content_hash = _converted_row(row)
        previous = seen.get(content_hash)
        if previous is not None:
            msg = (
                f"pricing snapshots {previous} and {row['id']} convert to the "
                f"same content hash {content_hash}"
            )
            raise CommandError(msg)
        seen[content_hash] = row["id"]
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
