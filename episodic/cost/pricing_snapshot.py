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
3
>>> snapshot.rates["input_tokens"].per_units
200000
"""

import dataclasses as dc
import datetime as dt
import re
import types
import typing as typ

from episodic.cost.pricing_snapshot_hash import pricing_snapshot_content_hash
from episodic.cost.pricing_snapshot_values import (
    MeteredRate,
    PricedService,
    PricingSubject,
    PricingSubjectFields,
    SourceDocument,
    UsageUnit,
    pricing_subject_of,
)
from episodic.cost.primitives import (
    CurrencyCode,
    PricingSourceKind,
    validate_currency_code,
)

if typ.TYPE_CHECKING:
    import collections.abc as cabc

__all__ = [
    "MeteredRate",
    "PricedService",
    "PricingSnapshot",
    "PricingSubject",
    "PricingSubjectFields",
    "SourceDocument",
    "UsageUnit",
    "pricing_subject_of",
]

_IDENTIFIER_KEY = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
# Metrics the system itself reports count tokens, so a card that denominates
# one of them in characters or milliseconds would price a token count with a
# rate for a different quantity. The list mirrors the legacy conversion table
# in migration 20261110_000017; a new token metric must be added in both places.
_TOKEN_METRICS = frozenset({
    "input_tokens",
    "output_tokens",
    "cached_input_tokens",
    "cache_write_tokens",
    "reasoning_tokens",
    "audio_input_tokens",
    "audio_output_tokens",
})


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
        if metric in _TOKEN_METRICS and rate.unit is not UsageUnit.TOKEN:
            msg = (
                f"rate for {metric!r} must be denominated in tokens, "
                f"not {rate.unit.value!r}."
            )
            raise ValueError(msg)
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
    """Immutable pricing inputs used to price one provider operation.

    Attributes
    ----------
    service_kind : PricedService
        Kind of service the snapshot prices.
    provider_name : str
        Provider the rates belong to; must not be blank.
    model : str
        Provider model or voice the rates apply to; must not be blank.
    operation : str
        Provider operation the rates price; must not be blank.
    source_kind : PricingSourceKind
        Whether the rates came from a provider rate card or an SLA4OAI plan.
    currency : CurrencyCode
        Three-letter uppercase ISO 4217 code the rates are denominated in.
    rates : Mapping[str, MeteredRate]
        Exact rate per usage metric, frozen on construction.
    retrieved_at : datetime
        Timezone-aware instant the rates were retrieved.
    effective_from : datetime or None
        Timezone-aware instant the rates take effect, when the source states
        one.
    source_document : SourceDocument or None
        Verbatim source document; required for an SLA4OAI plan.
    source_metadata : Mapping[str, str]
        Identifier-keyed provenance strings, frozen on construction.
    schema_version : int
        Canonical-form version; only ``1`` is understood.
    content_hash : str
        ``sha256:<hex>`` identity derived from the canonical form.

    Notes
    -----
    The content hash covers every field above except itself, so two snapshots
    with equal content are the same version and share one stored row. The
    billing period is deliberately absent: it belongs to run pins and ledger
    rows, not to the price.
    """

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
