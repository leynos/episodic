"""Immutable, content-addressed pricing snapshots.

A snapshot records exactly what a run was priced with: the service kind, the
priced subject, exact integer-fraction rates, provenance, and, when the source
is a service-level agreement, the verbatim document. Its identity is the
canonical content hash computed by `episodic.cost.pricing_snapshot_hash`, so a
row can never silently change meaning.

The mappings a caller passes in are copied into read-only proxies during
construction; later mutation of the caller's dictionaries cannot change a
snapshot or its hash.

Examples
--------
>>> rate = MeteredRate.reduced(15, 1_000_000, UsageUnit.TOKEN)
>>> snapshot = PricingSnapshot(
...     service_kind=PricedService.LLM,
...     provider_name="openai",
...     model="gpt-4o-mini",
...     operation="chat_completions",
...     source_kind=PricingSourceKind.PROVIDER_RATE_CARD,
...     currency=CurrencyCode("USD"),
...     rates={"input_tokens": rate},
...     retrieved_at=dt.datetime(2026, 5, 1, tzinfo=dt.UTC),
... )
>>> snapshot.rates["input_tokens"].amount_minor
15
"""

import dataclasses as dc
import datetime as dt
import enum
import hashlib
import math
import re
import types
import typing as typ

from episodic.cost.pricing_snapshot_hash import pricing_snapshot_content_hash
from episodic.cost.primitives import (
    CurrencyCode,
    PricingSourceKind,
    validate_currency_code,
)

if typ.TYPE_CHECKING:
    import collections.abc as cabc

_MAX_JSON_INT = 2**53 - 1
_MAX_SOURCE_DOCUMENT_BYTES = 262_144
_IDENTIFIER_KEY = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class PricedService(enum.StrEnum):
    """Kind of service a snapshot prices."""

    LLM = "llm"
    TTS = "tts"
    HELPER_SERVICE = "helper_service"


class UsageUnit(enum.StrEnum):
    """Unit each metered rate is expressed in."""

    TOKEN = "token"  # ruff: ignore[hardcoded-password-string]  # A usage unit, not a credential.
    CHARACTER = "character"
    MILLISECOND = "millisecond"
    REQUEST = "request"


def _is_json_int(value: object) -> bool:
    """Return whether a value is a non-boolean integer safe for canonical JSON."""
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and 0 <= value <= _MAX_JSON_INT
    )


@dc.dataclass(frozen=True, slots=True)
class MeteredRate:
    """Exact price of ``amount_minor`` minor units per ``per_units`` units."""

    amount_minor: int
    per_units: int
    unit: UsageUnit

    def __post_init__(self) -> None:
        """Reject out-of-range fractions and rates not in lowest terms."""
        if not _is_json_int(self.amount_minor):
            msg = f"amount_minor must be an integer in [0, {_MAX_JSON_INT}]."
            raise ValueError(msg)
        if not _is_json_int(self.per_units) or self.per_units == 0:
            msg = f"per_units must be an integer in [1, {_MAX_JSON_INT}]."
            raise ValueError(msg)
        if not isinstance(self.unit, UsageUnit):
            msg = f"unit must be a UsageUnit, not {type(self.unit).__name__}."
            raise TypeError(msg)
        if math.gcd(self.amount_minor, self.per_units) != 1:
            msg = (
                "rate must be in lowest terms: "
                f"{self.amount_minor}/{self.per_units}; "
                "use MeteredRate.reduced()."
            )
            raise ValueError(msg)

    @classmethod
    def reduced(
        cls,
        amount_minor: int,
        per_units: int,
        unit: UsageUnit,
    ) -> MeteredRate:
        """Build a rate normalized to lowest terms.

        Parameters
        ----------
        amount_minor : int
            Minor-unit amount; zero normalizes to ``0/1``.
        per_units : int
            Number of units the amount covers.
        unit : UsageUnit
            Unit the rate is expressed in.

        Returns
        -------
        MeteredRate
            Equivalent rate with the greatest common divisor removed.

        Raises
        ------
        ValueError
            If either integer is out of range or ``per_units`` is zero.
        """
        if not _is_json_int(amount_minor):
            msg = f"amount_minor must be an integer in [0, {_MAX_JSON_INT}]."
            raise ValueError(msg)
        if not _is_json_int(per_units) or per_units == 0:
            msg = f"per_units must be an integer in [1, {_MAX_JSON_INT}]."
            raise ValueError(msg)
        if amount_minor == 0:
            return cls(0, 1, unit)
        divisor = math.gcd(amount_minor, per_units)
        return cls(amount_minor // divisor, per_units // divisor, unit)


@dc.dataclass(frozen=True, slots=True)
class SourceDocument:
    """Verbatim source document carried beside a snapshot."""

    media_type: str
    content: str

    def __post_init__(self) -> None:
        """Reject blank media types and oversized content."""
        if not self.media_type.strip():
            msg = "source document media_type must not be blank."
            raise ValueError(msg)
        if len(self.content.encode("utf-8")) > _MAX_SOURCE_DOCUMENT_BYTES:
            msg = (
                "source document content must be at most "
                f"{_MAX_SOURCE_DOCUMENT_BYTES} UTF-8 bytes."
            )
            raise ValueError(msg)

    @property
    def sha256(self) -> str:
        """The ``sha256:<hex>`` digest of the UTF-8 content."""
        digest = hashlib.sha256(self.content.encode("utf-8")).hexdigest()
        return f"sha256:{digest}"


@dc.dataclass(frozen=True, slots=True)
class PricingSubject:
    """What a snapshot prices: service kind, provider, model, and operation."""

    service_kind: PricedService
    provider_name: str
    model: str
    operation: str


class PricingSubjectFields(typ.Protocol):
    """The four fields every priced subject is built from."""

    service_kind: PricedService
    provider_name: str
    model: str
    operation: str


def pricing_subject_of(source: PricingSubjectFields) -> PricingSubject:
    """Build the priced subject described by a snapshot or pinned operation.

    Parameters
    ----------
    source : PricingSubjectFields
        Value carrying a service kind, provider, model, and operation.

    Returns
    -------
    PricingSubject
        Subject assembled from those four fields.
    """
    return PricingSubject(
        service_kind=source.service_kind,
        provider_name=source.provider_name,
        model=source.model,
        operation=source.operation,
    )


def _require_identifier(value: str, *, field: str) -> None:
    """Reject blank or non-identifier names."""
    if not isinstance(value, str) or not _IDENTIFIER_KEY.fullmatch(value):
        msg = f"{field} must match ^[a-z][a-z0-9_]{{0,63}}$; got {value!r}."
        raise ValueError(msg)


def _require_non_blank(value: str, *, field: str) -> None:
    """Reject blank provider, model, and operation names."""
    if not isinstance(value, str) or not value.strip():
        msg = f"{field} must be a non-blank string."
        raise ValueError(msg)


def _require_aware(instant: dt.datetime, *, field: str) -> None:
    """Reject non-datetime and naive instants."""
    if not isinstance(instant, dt.datetime):
        msg = f"{field} must be a datetime."
        raise TypeError(msg)
    if instant.tzinfo is None:
        msg = f"{field} must be timezone-aware."
        raise ValueError(msg)


def _freeze_mapping(
    mapping: cabc.Mapping[str, typ.Any],
) -> cabc.Mapping[str, typ.Any]:
    """Return a read-only copy so callers cannot mutate snapshot state."""
    return types.MappingProxyType(dict(mapping))


def _validated_rates(
    rates: cabc.Mapping[str, MeteredRate],
) -> cabc.Mapping[str, MeteredRate]:
    """Return a frozen copy after checking every metric and rate."""
    frozen = _freeze_mapping(rates)
    for metric, rate in frozen.items():
        _require_identifier(metric, field="rate metric")
        if not isinstance(rate, MeteredRate):
            msg = f"rate for {metric!r} must be a MeteredRate."
            raise TypeError(msg)
    return frozen


def _validated_metadata(
    metadata: cabc.Mapping[str, str],
) -> cabc.Mapping[str, str]:
    """Return a frozen copy after checking every key and value."""
    frozen = _freeze_mapping(metadata)
    for key, value in frozen.items():
        _require_identifier(key, field="source_metadata key")
        if not isinstance(value, str):
            msg = f"source_metadata value for {key!r} must be a string."
            raise TypeError(msg)
    return frozen


@dc.dataclass(frozen=True, slots=True)
class PricingSnapshot:
    """Immutable pricing inputs used to price one provider operation."""

    service_kind: PricedService
    provider_name: str
    model: str
    operation: str
    source_kind: PricingSourceKind
    currency: CurrencyCode
    rates: cabc.Mapping[str, MeteredRate]
    retrieved_at: dt.datetime
    effective_from: dt.datetime | None = None
    source_document: SourceDocument | None = None
    source_metadata: cabc.Mapping[str, str] = dc.field(default_factory=dict)
    schema_version: int = 1
    content_hash: str = dc.field(init=False)

    def __post_init__(self) -> None:
        """Validate invariants, freeze mappings, and derive the content hash."""
        if self.schema_version != 1:
            msg = f"unsupported pricing snapshot schema_version {self.schema_version}."
            raise ValueError(msg)
        if not isinstance(self.service_kind, PricedService):
            msg = "service_kind must be a PricedService."
            raise TypeError(msg)
        if not isinstance(self.source_kind, PricingSourceKind):
            msg = "source_kind must be a PricingSourceKind."
            raise TypeError(msg)
        _require_non_blank(self.provider_name, field="provider_name")
        _require_non_blank(self.model, field="model")
        _require_non_blank(self.operation, field="operation")
        validate_currency_code(self.currency)
        _require_aware(self.retrieved_at, field="retrieved_at")
        if self.effective_from is not None:
            _require_aware(self.effective_from, field="effective_from")
        rates = _validated_rates(self.rates)
        source_metadata = _validated_metadata(self.source_metadata)
        self._validate_source(rates)
        object.__setattr__(self, "rates", rates)
        object.__setattr__(self, "source_metadata", source_metadata)
        object.__setattr__(self, "content_hash", pricing_snapshot_content_hash(self))

    def _validate_source(self, rates: cabc.Mapping[str, MeteredRate]) -> None:
        """Apply source-kind-specific requirements."""
        if self.source_kind is PricingSourceKind.PROVIDER_RATE_CARD and not rates:
            msg = "provider_rate_card snapshots must price at least one metric."
            raise ValueError(msg)
        if (
            self.source_kind is PricingSourceKind.SLA4OAI_PLAN
            and self.source_document is None
        ):
            msg = "sla4oai_plan snapshots must carry a source_document."
            raise ValueError(msg)

    @property
    def subject(self) -> PricingSubject:
        """The priced subject this snapshot applies to."""
        return pricing_subject_of(self)
