"""Resolve pricing snapshots from local YAML files.

Use ``FilePricingCatalogue`` for deterministic local deployments, tests, and
offline pricing snapshots. Other catalogue backends can use the same port when
pricing data comes from a database or provider API instead.

The adapter scans ``*.yaml`` and ``*.yml`` files under the configured directory,
parses each document into a ``PricingSnapshot``, and returns the latest
effective snapshot for a provider, model, operation, and billing period. Callers
should handle ``LookupError`` for missing prices and ``ValueError`` for malformed
snapshot files.
"""

import dataclasses as dc
import datetime as dt
import hashlib
import pathlib
import typing as typ

import yaml

from episodic.cost._time import parse_instant
from episodic.cost.ports import (
    BillingPeriodKey,
    CurrencyCode,
    PricingSnapshot,
    PricingSnapshotId,
    PricingSourceKind,
)

if typ.TYPE_CHECKING:
    import collections.abc as cabc

_default_pricing_directory = pathlib.Path("config/pricing-snapshots")
_timestamp_timezone_error = (
    "pricing snapshot timestamps must include timezone information."
)


def _default_now() -> str:
    """Return the current UTC instant as an ISO-8601 string."""
    return dt.datetime.now(dt.UTC).isoformat()


def _require_mapping(value: object, *, path: pathlib.Path) -> dict[str, object]:
    """Validate that a YAML document is an object."""
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        msg = f"Pricing snapshot {path} must contain a string-keyed YAML object."
        raise ValueError(msg)
    return typ.cast("dict[str, object]", value)


def _require_string(
    data: cabc.Mapping[str, object], key: str, path: pathlib.Path
) -> str:
    """Return a required string field."""
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        msg = f"Pricing snapshot {path} field {key!r} must be a non-empty string."
        raise ValueError(msg)
    return value.strip()


def _require_int_mapping(
    data: cabc.Mapping[str, object],
    key: str,
    path: pathlib.Path,
) -> dict[str, int]:
    """Return a required non-negative integer mapping."""
    value = data.get(key)
    if not isinstance(value, dict) or not all(isinstance(k, str) for k in value):
        msg = f"Pricing snapshot {path} field {key!r} must be a string-keyed mapping."
        raise ValueError(msg)
    result: dict[str, int] = {}
    for raw_metric, raw_rate in value.items():
        metric = typ.cast("str", raw_metric)
        if not _is_non_negative_int(raw_rate):
            msg = f"Pricing snapshot {path} metric {metric!r} must be non-negative int."
            raise ValueError(msg)
        result[metric] = typ.cast("int", raw_rate)
    return result


def _is_non_negative_int(value: object) -> bool:
    """Return whether value is a non-boolean non-negative integer."""
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _optional_string_mapping(
    data: cabc.Mapping[str, object],
    key: str,
    path: pathlib.Path,
) -> dict[str, str]:
    """Return an optional string mapping."""
    value = data.get(key, {})
    if not isinstance(value, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in value.items()
    ):
        msg = f"Pricing snapshot {path} field {key!r} must be a string mapping."
        raise ValueError(msg)
    return typ.cast("dict[str, str]", value)


@dc.dataclass(frozen=True, slots=True)
class _LoadedSnapshot:
    """Pricing snapshot plus effective timestamp used for resolution."""

    snapshot: PricingSnapshot
    effective_from: dt.datetime | None


@dc.dataclass(frozen=True, slots=True)
class _CatalogueLookup:
    """Pricing catalogue lookup dimensions."""

    provider_name: str
    model: str
    operation: str
    billing_period_key: BillingPeriodKey


class FilePricingCatalogue:
    """Resolve pricing snapshots from immutable YAML files."""

    def __init__(
        self,
        directory: str | pathlib.Path = _default_pricing_directory,
        *,
        now: cabc.Callable[[], str] = _default_now,
    ) -> None:
        self._directory = pathlib.Path(directory)
        self._now = now
        self._cache: list[_LoadedSnapshot] | None = None

    # The catalogue key is intentionally explicit across provider, model,
    # operation, and billing period so adapters cannot collapse dimensions.
    async def resolve(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        provider_name: str,
        model: str,
        operation: str,
        billing_period_key: BillingPeriodKey,
    ) -> PricingSnapshot:
        """Return the latest effective matching pricing snapshot."""
        now = parse_instant(
            self._now(),
            error_message=_timestamp_timezone_error,
        )
        lookup = _CatalogueLookup(
            provider_name=provider_name,
            model=model,
            operation=operation,
            billing_period_key=billing_period_key,
        )
        candidates = [
            loaded
            for loaded in self._load_snapshots()
            if self._matches_and_applicable(loaded, lookup, now)
        ]
        if not candidates:
            msg = (
                "No pricing snapshot found for "
                f"{provider_name}/{model}/{operation}/{billing_period_key}."
            )
            raise LookupError(msg)
        latest = max(
            candidates,
            key=lambda loaded: (
                loaded.effective_from or dt.datetime.min.replace(tzinfo=dt.UTC)
            ),
        )
        return latest.snapshot

    @staticmethod
    def _matches_and_applicable(
        loaded: _LoadedSnapshot,
        lookup: _CatalogueLookup,
        now: dt.datetime,
    ) -> bool:
        """Return whether a loaded snapshot matches the requested key."""
        return (
            loaded.snapshot.provider_name == lookup.provider_name
            and loaded.snapshot.model == lookup.model
            and loaded.snapshot.operation == lookup.operation
            and loaded.snapshot.billing_period_key == lookup.billing_period_key
            and (loaded.effective_from is None or loaded.effective_from <= now)
        )

    def _load_snapshots(self) -> list[_LoadedSnapshot]:
        """Load and cache all YAML snapshots from the configured directory."""
        if self._cache is not None:
            return self._cache
        if not self._directory.exists():
            self._cache = []
            return self._cache
        snapshots = [
            self._load_snapshot(path)
            for path in sorted((
                *self._directory.glob("*.yaml"),
                *self._directory.glob("*.yml"),
            ))
        ]
        self._cache = snapshots
        return snapshots

    @staticmethod
    def _load_snapshot(path: pathlib.Path) -> _LoadedSnapshot:
        """Load one YAML snapshot file."""
        raw_bytes = path.read_bytes()
        raw_data = yaml.safe_load(raw_bytes) or {}
        data = _require_mapping(raw_data, path=path)
        effective_from_value = data.get("effective_from")
        effective_from = (
            parse_instant(
                effective_from_value,
                error_message=_timestamp_timezone_error,
            )
            if isinstance(effective_from_value, str)
            else None
        )
        snapshot = PricingSnapshot(
            pricing_snapshot_id=PricingSnapshotId(
                _require_string(data, "pricing_snapshot_id", path)
            ),
            provider_name=_require_string(data, "provider_name", path),
            model=_require_string(data, "model", path),
            operation=_require_string(data, "operation", path),
            source_kind=PricingSourceKind(_require_string(data, "source_kind", path)),
            currency=CurrencyCode(_require_string(data, "currency", path)),
            billing_period_key=BillingPeriodKey(
                _require_string(data, "billing_period_key", path)
            ),
            rates_minor_per_metric=_require_int_mapping(
                data,
                "rates_minor_per_metric",
                path,
            ),
            source_metadata=_optional_string_mapping(data, "source_metadata", path),
            content_hash=hashlib.sha256(raw_bytes).hexdigest(),
            retrieved_at=_require_string(data, "retrieved_at", path),
        )
        return _LoadedSnapshot(snapshot=snapshot, effective_from=effective_from)
