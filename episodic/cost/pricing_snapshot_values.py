"""Value objects composed by immutable pricing snapshots.

`PricingSnapshot` is built from the service kind, the metered rate, the
optional verbatim source document, and the priced subject. Those values live
here so the snapshot module stays within the repository's file-size limit, and
so a port can name a priced subject without importing the snapshot itself.
"""

import dataclasses as dc
import enum
import hashlib
import math
import typing as typ

_MAX_JSON_INT = 2**53 - 1
_MAX_SOURCE_DOCUMENT_BYTES = 262_144


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
    """Exact price of ``amount_minor`` minor units per ``per_units`` units.

    Attributes
    ----------
    amount_minor : int
        Price in minor currency units, in ``[0, 2**53 - 1]``.
    per_units : int
        Number of usage units the price covers, in ``[1, 2**53 - 1]``.
    unit : UsageUnit
        Quantity the rate meters, such as tokens or characters.

    Notes
    -----
    The fraction is always in lowest terms so that equal prices share one
    canonical form and therefore one content hash. Use `reduced` to build a
    rate from an arbitrary amount and denominator.
    """

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
    """Verbatim source document carried beside a snapshot.

    Attributes
    ----------
    media_type : str
        Media type of the original document, such as ``application/yaml``.
    content : str
        Document text, at most 262 144 UTF-8 bytes.

    Notes
    -----
    The document is stored verbatim so a service-level agreement can be
    re-read exactly as it was priced. Its digest participates in the
    snapshot's content hash through `sha256`.
    """

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
    """What a snapshot prices: service kind, provider, model, and operation.

    Attributes
    ----------
    service_kind : PricedService
        Kind of service, such as ``llm`` or ``tts``.
    provider_name : str
        Provider the rates belong to.
    model : str
        Provider model or voice the rates apply to.
    operation : str
        Provider operation the rates price, such as ``chat_completions``.

    Notes
    -----
    Two snapshots with the same subject are different versions of the same
    price, which is what lets a run pin one version and later runs pick up a
    revision.
    """

    service_kind: PricedService
    provider_name: str
    model: str
    operation: str


class PricingSubjectFields(typ.Protocol):
    """The four fields every priced subject is built from.

    The members are read-only properties so a frozen snapshot and a mutable
    record both satisfy the protocol; a writable attribute would exclude the
    frozen value objects this protocol exists to describe.
    """

    @property
    def service_kind(self) -> PricedService:
        """Kind of service the subject prices."""
        ...

    @property
    def provider_name(self) -> str:
        """Provider that publishes the rate."""
        ...

    @property
    def model(self) -> str:
        """Model or voice the rate applies to."""
        ...

    @property
    def operation(self) -> str:
        """Provider operation the rate prices."""
        ...


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
