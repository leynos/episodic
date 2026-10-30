"""Validation helpers for the QA artefact domain model.

The QA value objects check a dozen small invariants from their
``__post_init__`` hooks. Those checks live here, rather than beside the
dataclasses, so that ``qa_artefacts`` stays within the project's module-size
ceiling and the rules can be read as one contract. ``_validate_citations``
stays with the models because it consults their public bounds.
"""

import datetime as dt
import decimal
import typing as typ

if typ.TYPE_CHECKING:
    import enum

# Rubric scores are stored as NUMERIC(5, 4), so the unit interval is enforced
# on the rounded value that would actually be persisted.
_RUBRIC_QUANTUM = decimal.Decimal("0.0001")
# Quantize under a fixed context. The caller's context may carry a narrow
# precision or an enabled Inexact trap, either of which would reject a score
# the column can hold.
_QUANTIZE_CONTEXT = decimal.Context(prec=28)


def _validate_enum_member(
    value: object,
    field_name: str,
    enum_type: type[enum.StrEnum],
) -> None:
    """Require an exact member of *enum_type*."""
    if not isinstance(value, enum_type):
        msg = f"{field_name} must be a {enum_type.__name__} value."
        raise TypeError(msg)


def _validate_bounded_text(value: str, field_name: str, limit: int) -> None:
    """Require a string no longer than *limit* characters."""
    if not isinstance(value, str):
        msg = f"{field_name} must be a string."
        raise TypeError(msg)
    if len(value) > limit:
        msg = f"{field_name} must be at most {limit} characters."
        raise ValueError(msg)


def _validate_non_negative_integer(value: int, field_name: str) -> None:
    """Require an exact non-negative integer, excluding booleans."""
    if type(value) is not int or value < 0:
        msg = f"{field_name} must be a non-negative integer."
        raise ValueError(msg)


def _validate_positive_integer(value: int, field_name: str) -> None:
    """Require an exact positive integer, excluding booleans."""
    if type(value) is not int or value < 1:
        msg = f"{field_name} must be a positive integer."
        raise ValueError(msg)


def _validate_optional_non_negative_integer(
    value: int | None,
    field_name: str,
) -> None:
    """Require an absent or non-negative integer value."""
    if value is not None:
        _validate_non_negative_integer(value, field_name)


def _validate_aware_datetime(value: dt.datetime, field_name: str) -> None:
    """Require a timezone-aware datetime."""
    if not isinstance(value, dt.datetime):
        msg = f"{field_name} must be a datetime."
        raise TypeError(msg)
    if value.tzinfo is None or value.utcoffset() is None:
        msg = f"{field_name} must be timezone-aware."
        raise ValueError(msg)


def _normalize_rubric_score(
    score: decimal.Decimal | None,
) -> decimal.Decimal | None:
    """Return *score* at the stored precision, rejecting unusable values."""
    if score is None:
        return None
    if not isinstance(score, decimal.Decimal):
        msg = "rubric_score must be a decimal.Decimal."
        raise TypeError(msg)
    if not score.is_finite():
        # PostgreSQL stores NaN in a NUMERIC column verbatim, so it would slip
        # past the interval check below and later fail an ordering comparison.
        msg = "rubric_score must be a finite decimal."
        raise ValueError(msg)
    try:
        with decimal.localcontext(_QUANTIZE_CONTEXT):
            rounded = score.quantize(
                _RUBRIC_QUANTUM,
                rounding=decimal.ROUND_HALF_EVEN,
            )
    except decimal.InvalidOperation as exc:
        msg = "rubric_score must be representable at four decimal places."
        raise ValueError(msg) from exc
    if rounded < 0 or rounded > 1:
        msg = (
            "rubric_score must lie within [0, 1] after rounding to four decimal places."
        )
        raise ValueError(msg)
    # A rounded negative zero compares equal to zero but serializes as -0.0.
    return rounded.copy_abs() if rounded.is_zero() else rounded
