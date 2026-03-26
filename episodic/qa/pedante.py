"""Pedante factuality and accuracy evaluator."""

from __future__ import annotations

import dataclasses as dc
import enum
import json
import typing as typ

from episodic.llm import (
    LLMPort,
    LLMProviderOperation,
    LLMRequest,
    LLMResponse,
    LLMTokenBudget,
    LLMUsage,
)


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
        for field_name in (
            "source_id",
            "citation_label",
            "tei_locator",
            "title",
            "excerpt",
        ):
            value = getattr(self, field_name)
            if value.strip() == "":
                msg = f"{field_name} must be non-empty."
                raise ValueError(msg)


@dc.dataclass(frozen=True, slots=True)
class PedanteEvaluationRequest:
    """Canonical Pedante request built from TEI plus cited source packets."""

    script_tei_xml: str
    sources: tuple[PedanteSourcePacket, ...]

    def __post_init__(self) -> None:
        """Reject blank TEI payloads and empty source lists."""
        if self.script_tei_xml.strip() == "":
            msg = "script_tei_xml must be non-empty."
            raise ValueError(msg)
        if len(self.sources) == 0:
            msg = "sources must contain at least one source packet."
            raise ValueError(msg)


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
        for field_name in ("claim_id", "claim_text", "summary", "remediation"):
            value = getattr(self, field_name)
            if value.strip() == "":
                msg = f"{field_name} must be non-empty."
                raise ValueError(msg)
        for source_id in self.cited_source_ids:
            if source_id.strip() == "":
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
        if self.summary.strip() == "":
            msg = "summary must be non-empty."
            raise ValueError(msg)

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
        data = _decode_object(payload)
        summary = _require_non_empty_string(data, "summary")
        raw_findings = _require_list(data, "findings")
        findings = tuple(_parse_finding(item) for item in raw_findings)
        return cls(
            summary=summary,
            findings=findings,
            usage=usage,
        )


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
        if self.model.strip() == "":
            msg = "model must be non-empty."
            raise ValueError(msg)
        if self.system_prompt.strip() == "":
            msg = "system_prompt must be non-empty."
            raise ValueError(msg)


@dc.dataclass(slots=True)
class PedanteEvaluator:
    """LLM-backed Pedante evaluator using the provider-neutral LLM port."""

    llm: LLMPort
    config: PedanteEvaluatorConfig

    @staticmethod
    def build_prompt(request: PedanteEvaluationRequest) -> str:
        """Render the Pedante prompt from the TEI-backed request."""
        prompt_payload = {
            "task": (
                "Inspect the TEI P5 script, identify claims, inspect the cited "
                "sources, and assess whether each claim is supported."
            ),
            "support_level_taxonomy": [level.value for level in SupportLevel],
            "severity_levels": [severity.value for severity in FindingSeverity],
            "claim_kinds": [claim_kind.value for claim_kind in ClaimKind],
            "script_tei_xml": request.script_tei_xml,
            "sources": [
                {
                    "source_id": source.source_id,
                    "citation_label": source.citation_label,
                    "tei_locator": source.tei_locator,
                    "title": source.title,
                    "excerpt": source.excerpt,
                }
                for source in request.sources
            ],
        }
        rendered_payload = json.dumps(prompt_payload, indent=2, ensure_ascii=True)
        return (
            "Evaluate the following TEI-backed script against its cited source "
            "packets. Return JSON only.\n"
            f"{rendered_payload}"
        )

    async def evaluate(
        self,
        request: PedanteEvaluationRequest,
    ) -> PedanteEvaluationResult:
        """Call the LLM port and parse strict Pedante findings."""
        response = await self.llm.generate(
            LLMRequest(
                model=self.config.model,
                prompt=self.build_prompt(request),
                system_prompt=self.config.system_prompt,
                provider_operation=self.config.provider_operation,
                token_budget=self.config.token_budget,
            )
        )
        return _result_from_response(response)


def _result_from_response(response: LLMResponse) -> PedanteEvaluationResult:
    """Parse a provider response into a Pedante evaluation result."""
    parsed = PedanteEvaluationResult.from_json(
        response.text,
        usage=response.usage,
    )
    return dc.replace(
        parsed,
        model=response.model,
        provider_response_id=response.provider_response_id,
        finish_reason=response.finish_reason,
    )


def _decode_object(payload: str) -> dict[str, object]:
    """Decode strict JSON into a mapping."""
    try:
        decoded = json.loads(payload)
    except json.JSONDecodeError as exc:
        msg = "Pedante response must be a valid JSON object."
        raise PedanteResponseFormatError(msg) from exc
    if not isinstance(decoded, dict):
        msg = "Pedante response must be a valid JSON object."
        raise PedanteResponseFormatError(msg)
    return typ.cast("dict[str, object]", decoded)


def _require_non_empty_string(payload: dict[str, object], field_name: str) -> str:
    """Read one required non-empty string field."""
    value = payload.get(field_name)
    if not isinstance(value, str) or value.strip() == "":
        msg = f"Pedante response field {field_name!r} must be a non-empty string."
        raise PedanteResponseFormatError(msg)
    return value


def _require_list(payload: dict[str, object], field_name: str) -> list[object]:
    """Read one required JSON list field."""
    value = payload.get(field_name)
    if not isinstance(value, list):
        msg = f"Pedante response field {field_name!r} must be a list."
        raise PedanteResponseFormatError(msg)
    return typ.cast("list[object]", value)


def _parse_finding(raw_finding: object) -> PedanteFinding:
    """Parse one finding mapping into a typed Pedante finding."""
    if not isinstance(raw_finding, dict):
        msg = "Each Pedante finding must be a JSON object."
        raise PedanteResponseFormatError(msg)
    finding = typ.cast("dict[str, object]", raw_finding)
    return PedanteFinding(
        claim_id=_require_non_empty_string(finding, "claim_id"),
        claim_text=_require_non_empty_string(finding, "claim_text"),
        claim_kind=_coerce_enum(
            ClaimKind,
            finding.get("claim_kind"),
            field_name="claim_kind",
        ),
        support_level=_coerce_enum(
            SupportLevel,
            finding.get("support_level"),
            field_name="support_level",
        ),
        severity=_coerce_enum(
            FindingSeverity,
            finding.get("severity"),
            field_name="severity",
        ),
        summary=_require_non_empty_string(finding, "summary"),
        remediation=_require_non_empty_string(finding, "remediation"),
        cited_source_ids=_coerce_string_tuple(finding, "cited_source_ids"),
    )


def _coerce_enum[TEnum: enum.StrEnum](
    enum_type: type[TEnum],
    raw_value: object,
    *,
    field_name: str,
) -> TEnum:
    """Convert one string value into a strict string enumeration."""
    if not isinstance(raw_value, str):
        msg = f"Pedante response field {field_name!r} must be a string."
        raise PedanteResponseFormatError(msg)
    try:
        return enum_type(raw_value)
    except ValueError as exc:
        msg = (
            f"Pedante response field {field_name!r} contained an unknown value: "
            f"{raw_value!r}."
        )
        raise PedanteResponseFormatError(msg) from exc


def _coerce_string_tuple(
    payload: dict[str, object],
    field_name: str,
) -> tuple[str, ...]:
    """Convert a required list of strings into a tuple."""
    raw_value = payload.get(field_name)
    if not isinstance(raw_value, list):
        msg = f"Pedante response field {field_name!r} must be a list of strings."
        raise PedanteResponseFormatError(msg)
    values: list[str] = []
    for item in raw_value:
        if not isinstance(item, str) or item.strip() == "":
            msg = (
                f"Pedante response field {field_name!r} must contain non-empty strings."
            )
            raise PedanteResponseFormatError(msg)
        values.append(item)
    return tuple(values)
