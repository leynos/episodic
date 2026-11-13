"""Canonical encoding and content hash for pricing snapshots.

Identity must not depend on incidental formatting: two snapshots that price the
same thing identically share a hash, and any change to a hashed field produces
a different one. Schema version 1 has its own field tuple and encoder, so a
later version can add fields without moving the hash of an existing row.

Examples
--------
>>> import datetime as dt
>>> from episodic.cost.pricing_snapshot import (
...     MeteredRate, PricedService, PricingSnapshot, UsageUnit,
... )
>>> from episodic.cost.primitives import CurrencyCode, PricingSourceKind
>>> snapshot = PricingSnapshot(
...     service_kind=PricedService.LLM,
...     provider_name="openai",
...     model="gpt-4o-mini",
...     operation="chat_completions",
...     source_kind=PricingSourceKind.PROVIDER_RATE_CARD,
...     currency=CurrencyCode("USD"),
...     rates={"input_tokens": MeteredRate.reduced(15, 1_000_000, UsageUnit.TOKEN)},
...     retrieved_at=dt.datetime(2026, 5, 1, tzinfo=dt.UTC),
... )
>>> pricing_snapshot_content_hash(snapshot).startswith("sha256:")
True
"""

import datetime as dt
import hashlib
import typing as typ

from episodic.json_canonicalization import canonical_json_bytes

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from episodic.cost.pricing_snapshot import MeteredRate, PricingSnapshot

PRICING_SNAPSHOT_V1_FIELDS: typ.Final = (
    "currency",
    "effective_from",
    "model",
    "operation",
    "provider_name",
    "rates",
    "retrieved_at",
    "schema_version",
    "service_kind",
    "source_document",
    "source_kind",
    "source_metadata",
)

_HASH_PREFIX = "sha256:"


def _format_instant(instant: dt.datetime) -> str:
    """Format an aware instant as UTC with six fractional digits."""
    # A tzinfo that reports no offset leaves the instant naive, and
    # ``astimezone`` would then read the host's local zone.
    if instant.tzinfo is None or instant.utcoffset() is None:
        msg = "pricing snapshot instants must be timezone-aware."
        raise ValueError(msg)
    # ``strftime("%Y")`` does not zero-pad years below 1000 on glibc, so the
    # same instant would encode differently on another platform. Formatting
    # each field keeps the year four digits wide everywhere.
    utc = instant.astimezone(dt.UTC)
    return (
        f"{utc.year:04d}-{utc.month:02d}-{utc.day:02d}"
        f"T{utc.hour:02d}:{utc.minute:02d}:{utc.second:02d}"
        f".{utc.microsecond:06d}Z"
    )


def canonical_rates(
    rates: cabc.Mapping[str, MeteredRate],
) -> dict[str, dict[str, object]]:
    """Serialize exact rates into their canonical JSON representation.

    Parameters
    ----------
    rates : collections.abc.Mapping[str, MeteredRate]
        Metric name to exact rate, already in lowest terms.

    Returns
    -------
    dict[str, dict[str, object]]
        JSON-compatible mapping with integer amounts and string units.

    Examples
    --------
    >>> rate = MeteredRate.reduced(15, 1_000_000, UsageUnit.TOKEN)
    >>> canonical_rates({"input_tokens": rate})
    {'input_tokens': {'amount_minor': 3, 'per_units': 200000, 'unit': 'token'}}
    """
    return {
        metric: {
            "amount_minor": rate.amount_minor,
            "per_units": rate.per_units,
            "unit": str(rate.unit),
        }
        for metric, rate in rates.items()
    }


def _canonical_v1_document(snapshot: PricingSnapshot) -> dict[str, object]:
    """Build the schema-version-1 canonical document."""
    rates = canonical_rates(snapshot.rates)
    source_document = (
        None
        if snapshot.source_document is None
        else {
            "media_type": snapshot.source_document.media_type,
            "sha256": snapshot.source_document.sha256,
        }
    )
    document: dict[str, object] = {
        "currency": str(snapshot.currency),
        "effective_from": (
            None
            if snapshot.effective_from is None
            else _format_instant(snapshot.effective_from)
        ),
        "model": snapshot.model,
        "operation": snapshot.operation,
        "provider_name": snapshot.provider_name,
        "rates": rates,
        "retrieved_at": _format_instant(snapshot.retrieved_at),
        "schema_version": snapshot.schema_version,
        "service_kind": str(snapshot.service_kind),
        "source_document": source_document,
        "source_kind": str(snapshot.source_kind),
        "source_metadata": dict(snapshot.source_metadata),
    }
    if tuple(sorted(document)) != tuple(sorted(PRICING_SNAPSHOT_V1_FIELDS)):
        msg = "version 1 canonical document must contain exactly the v1 fields."
        raise AssertionError(msg)
    return document


_ENCODERS: typ.Final[
    cabc.Mapping[int, cabc.Callable[[PricingSnapshot], dict[str, object]]]
] = {1: _canonical_v1_document}


def canonical_pricing_document(snapshot: PricingSnapshot) -> dict[str, object]:
    """Return the canonical document hashed for a snapshot.

    Parameters
    ----------
    snapshot : PricingSnapshot
        Snapshot to encode.

    Returns
    -------
    dict[str, object]
        JSON-compatible document holding exactly the fields the snapshot's
        schema version hashes.

    Raises
    ------
    ValueError
        If no canonical encoder is registered for the snapshot's schema
        version.
    """
    encoder = _ENCODERS.get(snapshot.schema_version)
    if encoder is None:
        msg = (
            "no canonical encoder for pricing snapshot schema "
            f"{snapshot.schema_version}."
        )
        raise ValueError(msg)
    return encoder(snapshot)


def pricing_snapshot_content_hash(snapshot: PricingSnapshot) -> str:
    """Return the ``sha256:<hex>`` identity of a snapshot.

    Parameters
    ----------
    snapshot : PricingSnapshot
        Snapshot to hash.

    Returns
    -------
    str
        Lowercase hexadecimal digest prefixed with ``sha256:``.
    """
    document = canonical_pricing_document(snapshot)
    digest = hashlib.sha256(canonical_json_bytes(document)).hexdigest()
    return f"{_HASH_PREFIX}{digest}"
