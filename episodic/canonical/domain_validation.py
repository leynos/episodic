"""Shared validation helpers for canonical domain value objects.

These private helpers are called from the ``__post_init__`` hooks of several
dataclasses spread across the ``domain_*`` modules. They live here, rather
than alongside any single dataclass, so that every dataclass module can
depend on them without importing from another dataclass module.
"""

from .generation_quality import QaStatus, QualityMode


def _require_positive_integer(value: object, field_name: str) -> None:
    """Require an exact positive integer, excluding boolean values."""
    if type(value) is not int or value < 1:
        msg = f"{field_name} must be a positive integer."
        raise ValueError(msg)


def _require_value(value: object, field_name: str) -> None:
    """Require a non-null provenance value."""
    if value is None:
        msg = f"{field_name} must be set."
        raise ValueError(msg)


def _is_blank(value: str) -> bool:
    """Return whether a string is empty after whitespace trimming."""
    return value.strip() == ""


def _validate_non_empty_text(value: str, field_name: str) -> None:
    """Validate a required non-empty string field."""
    if not isinstance(value, str):
        msg = f"{field_name} must be a string."
        raise TypeError(msg)
    if _is_blank(value):
        msg = f"{field_name} must be a non-empty string."
        raise ValueError(msg)


def _validate_optional_text(value: str | None, field_name: str) -> None:
    """Validate an optional string field when present."""
    if value is not None:
        _validate_non_empty_text(value, field_name)


def _validate_draft_without_qa_metadata(
    *,
    quality_mode: QualityMode,
    qa_status: QaStatus | None,
    skip_qa_rationale: str | None,
) -> None:
    """Validate the no-QA slice's required audit metadata."""
    if quality_mode is not QualityMode.DRAFT_WITHOUT_QA:
        msg = f"Unsupported quality_mode: {quality_mode!s}."
        raise ValueError(msg)
    if qa_status is not QaStatus.SKIPPED:
        msg = "qa_status must be skipped for draft_without_qa runs."
        raise ValueError(msg)
    if skip_qa_rationale is None:
        msg = "skip_qa_rationale must be a non-empty string."
        raise ValueError(msg)
    _validate_non_empty_text(skip_qa_rationale, "skip_qa_rationale")


def _copy_json_mapping(owner: object, field_name: str) -> None:
    """Validate and defensively copy a JSON mapping field."""
    value = getattr(owner, field_name)
    if not isinstance(value, dict):
        msg = f"{field_name} must be a JSON mapping."
        raise TypeError(msg)
    object.__setattr__(owner, field_name, dict(value))
