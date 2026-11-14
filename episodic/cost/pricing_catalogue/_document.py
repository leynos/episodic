"""Parse one schema-version-1 pricing card from YAML.

The parser is deliberately strict: a legacy document, an unknown key, or a
malformed rate fails with `PricingCatalogueError` naming the file, so a bad
catalogue stops the process at startup rather than mispricing a run.

Examples
--------
>>> snapshot = load_snapshot(pathlib.Path("config/pricing-snapshots/card.yaml"))
>>> snapshot.schema_version
1
"""

import decimal
import math
import typing as typ

import yaml

from episodic.cost._time import parse_instant
from episodic.cost.pricing_snapshot import (
    MeteredRate,
    PricedService,
    PricingSnapshot,
    SourceDocument,
    UsageUnit,
)
from episodic.cost.primitives import CurrencyCode, PricingSourceKind

from ._errors import PricingCatalogueError
from ._yaml_loader import _UniqueKeyLoader

if typ.TYPE_CHECKING:
    import collections.abc as cabc
    import datetime as dt
    import pathlib

_LEGACY_KEYS = frozenset({"pricing_snapshot_id", "billing_period_key"})
_LEGACY_RATE_KEY = "rates_minor_per_metric"
_CONVERSION_GUIDANCE = (
    "Convert the card to schema version 1; see ADR-028 and the rate-card "
    "conversion section of docs/users-guide.md."
)
_REQUIRED_KEYS = frozenset({
    "schema_version",
    "service_kind",
    "provider_name",
    "model",
    "operation",
    "source_kind",
    "currency",
    "rates",
    "retrieved_at",
})
_OPTIONAL_KEYS = frozenset({"source_metadata", "effective_from"})
_RATE_KEYS = frozenset({"amount_minor", "per_units", "unit"})
_TIMESTAMP_ERROR = "pricing snapshot timestamps must include timezone information."
# A decimal string can name an exponent far larger than any price: ``1e999999999``
# would make ``as_integer_ratio`` build a billion-digit integer. No representable
# rate needs more than a few dozen decimal places, so a larger exponent is a
# malformed card rather than a price.
_MAX_DECIMAL_EXPONENT = 30


def _fail(path: pathlib.Path, message: str) -> typ.NoReturn:
    """Raise a catalogue error naming the offending file."""
    msg = f"Pricing snapshot {path}: {message}"
    raise PricingCatalogueError(msg)


def _require_mapping(
    value: object,
    *,
    path: pathlib.Path,
    field: str,
) -> dict[str, object]:
    """Return a string-keyed mapping or fail naming the file."""
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        _fail(path, f"field {field!r} must be a string-keyed mapping.")
    return typ.cast("dict[str, object]", value)


def _string_field(
    data: cabc.Mapping[str, object],
    key: str,
    path: pathlib.Path,
    *,
    required: bool,
) -> str | None:
    """Return a non-blank string field, honouring required/optional presence."""
    value = data.get(key)
    # A missing field is only an error when the caller requires it, and a
    # present field must always hold a non-blank string.
    if value is None and required:
        _fail(path, f"field {key!r} must be a non-empty string.")
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        qualifier = "" if required else " when present"
        _fail(path, f"field {key!r} must be a non-empty string{qualifier}.")
    return value.strip()


def _require_string(
    data: cabc.Mapping[str, object], key: str, path: pathlib.Path
) -> str:
    """Return a required non-blank string field."""
    return typ.cast("str", _string_field(data, key, path, required=True))


def _optional_string(
    data: cabc.Mapping[str, object],
    key: str,
    path: pathlib.Path,
) -> str | None:
    """Return an optional non-blank string field."""
    return _string_field(data, key, path, required=False)


def _require_int(data: cabc.Mapping[str, object], key: str, path: pathlib.Path) -> int:
    """Return a required non-boolean integer field."""
    value = data.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        _fail(path, f"field {key!r} must be an integer.")
    return value


def _is_string_mapping(value: object) -> bool:
    """Return whether a value is a mapping of strings to strings."""
    return isinstance(value, dict) and all(
        isinstance(item_key, str) and isinstance(item_value, str)
        for item_key, item_value in value.items()
    )


def _string_mapping(
    data: cabc.Mapping[str, object],
    key: str,
    path: pathlib.Path,
) -> dict[str, str]:
    """Return an optional string-to-string mapping."""
    value = data.get(key, {})
    if not _is_string_mapping(value):
        _fail(path, f"field {key!r} must be a string mapping.")
    return typ.cast("dict[str, str]", value)


def _decimal_amount(amount: str, path: pathlib.Path, metric: str) -> decimal.Decimal:
    """Parse a decimal-string amount and reject a value a rate cannot hold."""
    try:
        value = decimal.Decimal(amount)
    except decimal.InvalidOperation:
        _fail(path, f"rate {metric!r} amount_minor {amount!r} is not a decimal.")
    if not value.is_finite() or value < 0:
        _fail(path, f"rate {metric!r} amount_minor must be finite and non-negative.")
    exponent = value.as_tuple().exponent
    if isinstance(exponent, int) and abs(exponent) > _MAX_DECIMAL_EXPONENT:
        _fail(path, f"rate {metric!r} amount_minor exponent is out of range.")
    return value


def _amount_fraction(
    amount: object, path: pathlib.Path, metric: str
) -> tuple[int, int]:
    """Convert an integer or decimal-string amount to an exact fraction."""
    if isinstance(amount, bool):
        _fail(path, f"rate {metric!r} amount_minor must be a number.")
    if isinstance(amount, int):
        return amount, 1
    if not isinstance(amount, str):
        _fail(path, f"rate {metric!r} amount_minor must be an integer or string.")
    return _decimal_amount(amount, path, metric).as_integer_ratio()


def _parse_rate(
    metric: str,
    value: object,
    path: pathlib.Path,
) -> MeteredRate:
    """Parse one metric rate into an exact lowest-terms fraction."""
    rate = _require_mapping(value, path=path, field=f"rates.{metric}")
    unknown = set(rate) - _RATE_KEYS
    if unknown:
        joined = ", ".join(sorted(unknown))
        _fail(path, f"unknown fields in rate {metric!r}: {joined}.")
    amount, amount_denominator = _amount_fraction(
        rate.get("amount_minor"),
        path,
        metric,
    )
    per_units = _require_int(rate, "per_units", path)
    # A zero denominator is a card error, not a crash: `math.gcd(0, 0)` is zero,
    # so the reduction below would divide by zero and escape the documented
    # PricingCatalogueError contract without naming the file.
    if per_units <= 0:
        _fail(path, f"rate {metric!r} per_units must be positive.")
    unit_value = _require_string(rate, "unit", path)
    try:
        unit = UsageUnit(unit_value)
    except ValueError:
        _fail(path, f"rate {metric!r} unit {unit_value!r} is not supported.")
    # Reduce before the value object bounds the parts, so a decimal amount that
    # only clears the canonical integer limit by carrying a large denominator
    # is accepted on its exact price rather than on how it was written.
    denominator = per_units * amount_denominator
    divisor = math.gcd(amount, denominator)
    return MeteredRate.reduced(amount // divisor, denominator // divisor, unit)


def _parse_rates(
    data: cabc.Mapping[str, object],
    path: pathlib.Path,
) -> dict[str, MeteredRate]:
    """Parse the required rate map."""
    raw_rates = _require_mapping(data.get("rates"), path=path, field="rates")
    return {
        metric: _parse_rate(metric, value, path) for metric, value in raw_rates.items()
    }


def _parse_instant(value: str, path: pathlib.Path) -> dt.datetime:
    """Parse one instant, naming the file when the timezone is missing."""
    try:
        return parse_instant(value, error_message=_TIMESTAMP_ERROR)
    except ValueError as exc:
        _fail(path, str(exc))


def _require_instant_field(
    data: cabc.Mapping[str, object],
    key: str,
    path: pathlib.Path,
) -> dt.datetime:
    """Parse a required instant field."""
    return _parse_instant(_require_string(data, key, path), path)


def _optional_instant_field(
    data: cabc.Mapping[str, object],
    key: str,
    path: pathlib.Path,
) -> dt.datetime | None:
    """Parse an optional instant field."""
    value = _optional_string(data, key, path)
    if value is None:
        return None
    return _parse_instant(value, path)


def _reject_legacy_document(
    data: cabc.Mapping[str, object],
    path: pathlib.Path,
) -> None:
    """Reject a pre-v1 card rather than silently misreading it."""
    legacy = _LEGACY_KEYS & set(data)
    if _LEGACY_RATE_KEY in data:
        legacy |= {_LEGACY_RATE_KEY}
    if legacy:
        joined = ", ".join(sorted(legacy))
        _fail(
            path,
            f"legacy document fields are not supported: {joined}. "
            f"{_CONVERSION_GUIDANCE}",
        )


def _reject_unknown_keys(data: cabc.Mapping[str, object], path: pathlib.Path) -> None:
    """Reject keys the schema version does not define."""
    unknown = set(data) - _REQUIRED_KEYS - _OPTIONAL_KEYS
    if unknown:
        joined = ", ".join(sorted(unknown))
        _fail(path, f"unknown fields: {joined}.")


def _source_document(
    data: cabc.Mapping[str, object],
    raw_text: str,
) -> SourceDocument | None:
    """Return the verbatim document for a service-level agreement card."""
    if data.get("source_kind") != PricingSourceKind.SLA4OAI_PLAN.value:
        return None
    return SourceDocument(media_type="application/yaml", content=raw_text)


def _read_card(path: pathlib.Path) -> str:
    """Read the card text, keeping CRLF bytes for verbatim storage."""
    try:
        # Keep CRLF bytes: an SLA4OAI card is stored verbatim, and its digest
        # must cover the bytes that were read, not a translated copy.
        return path.read_text(encoding="utf-8", newline="")
    except (OSError, UnicodeDecodeError) as exc:
        # Both failures must name the card: a startup traceback otherwise
        # leaves the operator without the offending path.
        _fail(path, f"cannot read card: {exc}")


def _load_yaml(raw_text: str, path: pathlib.Path) -> object:
    """Parse the card text, naming the file for any YAML failure."""
    try:
        # The reader rejects some bytes, such as NUL, while the loader is being
        # constructed, so construction belongs inside the card-naming boundary.
        loader = _UniqueKeyLoader(raw_text)
    except yaml.YAMLError as exc:
        _fail(path, f"invalid YAML: {exc}")
    try:
        return loader.get_single_data() or {}
    except (yaml.YAMLError, ValueError) as exc:
        # An impossible timestamp such as 2026-02-30 raises ValueError here.
        _fail(path, f"invalid YAML: {exc}")
    finally:
        loader.dispose()


def _reject_missing_keys(data: cabc.Mapping[str, object], path: pathlib.Path) -> None:
    """Reject a document that omits a required field."""
    missing = _REQUIRED_KEYS - set(data)
    if missing:
        joined = ", ".join(sorted(missing))
        _fail(path, f"missing required fields: {joined}.")


def _build_snapshot(
    data: cabc.Mapping[str, object],
    raw_text: str,
    path: pathlib.Path,
) -> PricingSnapshot:
    """Construct the snapshot, naming the file when a value is rejected."""
    try:
        return PricingSnapshot(
            service_kind=PricedService(_require_string(data, "service_kind", path)),
            provider_name=_require_string(data, "provider_name", path),
            model=_require_string(data, "model", path),
            operation=_require_string(data, "operation", path),
            source_kind=PricingSourceKind(_require_string(data, "source_kind", path)),
            currency=CurrencyCode(_require_string(data, "currency", path)),
            rates=_parse_rates(data, path),
            source_metadata=_string_mapping(data, "source_metadata", path),
            retrieved_at=_require_instant_field(data, "retrieved_at", path),
            effective_from=_optional_instant_field(data, "effective_from", path),
            source_document=_source_document(data, raw_text),
            schema_version=_require_int(data, "schema_version", path),
        )
    except PricingCatalogueError:
        raise
    except (TypeError, ValueError) as exc:
        _fail(path, str(exc))


def load_snapshot(path: pathlib.Path) -> PricingSnapshot:
    """Load one schema-version-1 pricing card.

    Parameters
    ----------
    path : pathlib.Path
        YAML file to parse.

    Returns
    -------
    PricingSnapshot
        Immutable snapshot described by the file.

    Raises
    ------
    PricingCatalogueError
        If the file cannot be read or is not a valid schema-version-1 card.
    """  # ruff: ignore[docstring-extraneous-exception]  # Raised in private helpers.
    raw_text = _read_card(path)
    data = _require_mapping(_load_yaml(raw_text, path), path=path, field="document")
    _reject_legacy_document(data, path)
    _reject_unknown_keys(data, path)
    _reject_missing_keys(data, path)
    return _build_snapshot(data, raw_text, path)
