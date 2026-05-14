"""Pedante evaluator contracts and response DTOs.

The Pedante QA pipeline exchanges immutable request and response objects while
checking scripted podcast claims against cited source packets.  This module
defines the public contracts used by evaluator implementations, prompt builders,
and tests: ``PedanteEvaluationRequest`` carries TEI plus source evidence,
``PedanteFinding`` models one claim-level result, ``PedanteEvaluationResult``
collects typed findings and provider metadata, and ``PedanteEvaluatorConfig``
describes one invocation.

Typical flow is to build a ``PedanteEvaluationRequest``, pass it to an evaluator
port, then inspect the typed result for blocking findings:

Examples
--------
>>> packet = PedanteSourcePacket(
...     source_id="src-1",
...     citation_label="Source 1",
...     tei_locator="#s1",
...     title="Archive note",
...     excerpt="Evidence text.",
... )
>>> request = PedanteEvaluationRequest("<TEI/>", (packet,))
>>> request.sources[0].source_id
'src-1'
"""

import collections.abc as cabc
import dataclasses as dc
import enum

from episodic.llm import LLMProviderOperation, LLMTokenBudget, LLMUsage


def _ensure_non_empty_fields(instance: object, *field_names: str) -> None:
    """Reject blank or whitespace-only string fields on a dataclass instance."""
    for field_name in field_names:
        value = getattr(instance, field_name)
        if not isinstance(value, str):
            msg = f"{field_name} must be a string."
            raise TypeError(msg)
        if not value.strip():
            msg = f"{field_name} must be non-empty."
            raise ValueError(msg)


def _require_non_empty_string_field(value: object, field_name: str) -> None:
    """Reject non-string or blank string field values."""
    if not isinstance(value, str):
        msg = f"{field_name} must be a string."
        raise TypeError(msg)
    if not value.strip():
        msg = f"{field_name} must be non-empty."
        raise ValueError(msg)


def _require_non_empty_tuple_field(value: object, field_name: str) -> None:
    """Reject non-tuple or empty tuple field values."""
    if not isinstance(value, tuple):
        msg = f"{field_name} must be a tuple of source packets."
        raise TypeError(msg)
    if not value:
        msg = f"{field_name} must contain at least one source packet."
        raise ValueError(msg)


def _require_source_packet_items(value: tuple[object, ...], field_name: str) -> None:
    """Reject source tuples containing non-source-packet items."""
    for item in value:
        if not isinstance(item, PedanteSourcePacket):
            msg = f"{field_name} must contain PedanteSourcePacket values."
            raise TypeError(msg)


def _require_enum_field(
    value: object,
    enum_type: type[enum.Enum],
    field_name: str,
) -> None:
    """Reject values that are not members of the expected enum."""
    if not isinstance(value, enum_type):
        msg = f"{field_name} must be a {enum_type.__name__}."
        raise TypeError(msg)


def _coerce_findings_tuple(value: object) -> tuple[PedanteFinding, ...]:
    """Return immutable Pedante findings after validating every item."""
    if not isinstance(value, cabc.Sequence) or isinstance(
        value, (str, bytes, bytearray)
    ):
        msg = "findings must be a sequence of PedanteFinding values."
        raise TypeError(msg)
    findings: list[PedanteFinding] = []
    for finding in value:
        if not isinstance(finding, PedanteFinding):
            msg = "findings must contain PedanteFinding values."
            raise TypeError(msg)
        findings.append(finding)
    return tuple(findings)


def _require_usage(value: object) -> None:
    """Reject usage metadata that is not normalized LLM usage."""
    if value is not None and not isinstance(value, LLMUsage):
        msg = "usage must be an LLMUsage value."
        raise TypeError(msg)


class ClaimKind(enum.StrEnum):
    """Kinds of claims Pedante can evaluate."""

    DIRECT_QUOTE = "direct_quote"
    TRANSPLANTED_CLAIM = "transplanted_claim"
    INFERENCE = "inference"


class SupportLevel(enum.StrEnum):
    """How strongly the cited source material supports a claim."""

    CITATION_ABSENT = "citation_absent"
    MISQUOTATION = "misquotation"
    ACCURATE_QUOTATION = "accurate_quotation"
    MISINTERPRETED_CLAIM = "misinterpreted_claim"
    FABRICATED_CLAIM = "fabricated_claim"
    PLAUSIBLE_REINTERPRETATION = "plausible_reinterpretation"
    ACCURATE_RESTATEMENT = "accurate_restatement"
    INFERENCE_NOT_SUPPORTED = "inference_not_supported"
    INACCURATE_REINTERPRETATION = "inaccurate_reinterpretation"
    INFERENCE_SUPPORTED_WITH_IRRELEVANT_SOURCES = (
        "inference_supported_with_irrelevant_sources"
    )
    INFERENCE_PLAUSIBLY_SUPPORTED = "inference_plausibly_supported"
    INFERENCE_DIRECTLY_SUPPORTED = "inference_directly_supported"
    CONTRADICTORY_CLAIMS_IN_DOCUMENT = "contradictory_claims_in_document"


_BLOCKING_SUPPORT_LEVELS = frozenset({
    SupportLevel.CITATION_ABSENT,
    SupportLevel.MISQUOTATION,
    SupportLevel.MISINTERPRETED_CLAIM,
    SupportLevel.FABRICATED_CLAIM,
    SupportLevel.INFERENCE_NOT_SUPPORTED,
    SupportLevel.INACCURATE_REINTERPRETATION,
    SupportLevel.INFERENCE_SUPPORTED_WITH_IRRELEVANT_SOURCES,
    SupportLevel.CONTRADICTORY_CLAIMS_IN_DOCUMENT,
})


class FindingSeverity(enum.StrEnum):
    """Editorial severity level for one Pedante finding."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dc.dataclass(frozen=True, slots=True)
class PedanteSourcePacket:
    """Source packet supplied to Pedante as evidence for one or more claims."""

    source_id: str
    citation_label: str
    tei_locator: str
    title: str
    excerpt: str

    def __post_init__(self) -> None:
        """Reject blank source packet fields."""
        _ensure_non_empty_fields(
            self, "source_id", "citation_label", "tei_locator", "title", "excerpt"
        )


@dc.dataclass(frozen=True, slots=True)
class PedanteEvaluationRequest:
    """Canonical Pedante request built from TEI plus cited source packets."""

    script_tei_xml: str
    sources: tuple[PedanteSourcePacket, ...]

    def __post_init__(self) -> None:
        """Reject blank TEI payloads and empty source lists."""
        _require_non_empty_string_field(self.script_tei_xml, "script_tei_xml")
        _require_non_empty_tuple_field(self.sources, "sources")
        _require_source_packet_items(self.sources, "sources")


@dc.dataclass(frozen=True, slots=True)
class PedanteFinding:
    """One claim-level Pedante finding."""

    claim_id: str
    claim_text: str
    claim_kind: ClaimKind
    support_level: SupportLevel
    severity: FindingSeverity
    summary: str
    remediation: str
    cited_source_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        """Reject blank claim identifiers and prose fields."""
        _require_enum_field(self.claim_kind, ClaimKind, "claim_kind")
        _require_enum_field(self.support_level, SupportLevel, "support_level")
        _require_enum_field(self.severity, FindingSeverity, "severity")
        _ensure_non_empty_fields(
            self, "claim_id", "claim_text", "summary", "remediation"
        )
        if not isinstance(self.cited_source_ids, tuple):
            msg = "cited_source_ids must be a tuple of string values."
            raise TypeError(msg)
        for source_id in self.cited_source_ids:
            if not isinstance(source_id, str):
                msg = "cited_source_ids must contain string values."
                raise TypeError(msg)
            if not source_id.strip():
                msg = "cited_source_ids must not contain blank values."
                raise ValueError(msg)

    @property
    def is_blocking(self) -> bool:
        """Return whether the finding should force a refinement loop."""
        return self.support_level in _BLOCKING_SUPPORT_LEVELS


@dc.dataclass(frozen=True, slots=True)
class PedanteEvaluationResult:
    """Typed Pedante findings plus normalized provider metadata."""

    summary: str
    findings: tuple[PedanteFinding, ...]
    usage: LLMUsage
    model: str = ""
    provider_response_id: str = ""
    finish_reason: str | None = None

    def __post_init__(self) -> None:
        """Reject blank summaries."""
        object.__setattr__(
            self,
            "findings",
            _coerce_findings_tuple(self.findings),
        )
        _require_usage(self.usage)
        _ensure_non_empty_fields(self, "summary")

    @property
    def requires_revision(self) -> bool:
        """Return whether any finding blocks editorial approval."""
        return any(finding.is_blocking for finding in self.findings)

    @classmethod
    def from_json(
        cls,
        payload: str,
        *,
        usage: LLMUsage,
    ) -> PedanteEvaluationResult:
        """Parse strict Pedante JSON into a typed result."""
        from .parsing import _evaluation_result_from_json

        return _evaluation_result_from_json(cls, payload, usage=usage)


class PedanteResponseFormatError(ValueError):
    """Raised when Pedante cannot parse structured evaluator output."""


@dc.dataclass(frozen=True, slots=True)
class PedanteEvaluatorConfig:
    """Configuration for one Pedante evaluator invocation."""

    model: str
    provider_operation: LLMProviderOperation | str = (
        LLMProviderOperation.CHAT_COMPLETIONS
    )
    token_budget: LLMTokenBudget | None = None
    system_prompt: str = (
        "You are Pedante, the factuality evaluator for scripted podcasts. "
        "Identify claim-level factual support issues against the provided TEI "
        "script and cited sources. Please return JSON only with keys summary and "
        "findings. Each finding must include claim_id, claim_text, claim_kind, "
        "support_level, severity, summary, remediation, and cited_source_ids."
    )

    def __post_init__(self) -> None:
        """Reject blank model names and system prompts."""
        _ensure_non_empty_fields(self, "model", "system_prompt")
