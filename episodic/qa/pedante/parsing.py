"""Strict Pedante response JSON parsing."""

import enum
import json
import typing as typ
from typing import TypeVar  # noqa: ICN003

from .types import (
    ClaimKind,
    FindingSeverity,
    PedanteEvaluationResult,
    PedanteFinding,
    PedanteResponseFormatError,
    SupportLevel,
)

if typ.TYPE_CHECKING:
    from episodic.llm import LLMUsage


def _evaluation_result_from_json(
    result_type: type[PedanteEvaluationResult],
    payload: str,
    *,
    usage: LLMUsage,
) -> PedanteEvaluationResult:
    """Parse strict Pedante JSON into a typed result instance."""
    data = _decode_object(payload)
    summary = _require_non_empty_string(data, "summary")
    raw_findings = _require_list(data, "findings")
    findings = tuple(_parse_finding(item) for item in raw_findings)
    return result_type(
        summary=summary,
        findings=findings,
        usage=usage,
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
    if not isinstance(value, str) or not value.strip():
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


_TEnum = TypeVar("_TEnum", bound=enum.StrEnum)


def _coerce_enum(  # noqa: UP047
    enum_type: type[_TEnum],
    raw_value: object,
    *,
    field_name: str,
) -> _TEnum:
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


def _require_non_empty_string_item(item: object, field_name: str) -> str:
    """Validate that a single list element is a non-empty string."""
    if not isinstance(item, str) or not item.strip():
        msg = f"Pedante response field {field_name!r} must contain non-empty strings."
        raise PedanteResponseFormatError(msg)
    return item


def _coerce_string_tuple(
    payload: dict[str, object],
    field_name: str,
) -> tuple[str, ...]:
    """Convert a required list of strings into a tuple."""
    raw_value = payload.get(field_name)
    if not isinstance(raw_value, list):
        msg = f"Pedante response field {field_name!r} must be a list of strings."
        raise PedanteResponseFormatError(msg)
    return tuple(_require_non_empty_string_item(item, field_name) for item in raw_value)
