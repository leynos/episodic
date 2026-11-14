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

# The domain holds rubric scores at four decimal places, so the unit interval
# is enforced on the rounded value rather than on the raw input.
_RUBRIC_QUANTUM = decimal.Decimal("0.0001")
# Scores just outside the unit interval still round into it, so this window is
# the accepted domain the CrossHair contract below quantifies over.
_RUBRIC_TOLERANCE = decimal.Decimal("0.00005")
_RUBRIC_LOW = -_RUBRIC_TOLERANCE
_RUBRIC_HIGH = decimal.Decimal(1) + _RUBRIC_TOLERANCE
# Quantize under a fixed context. The caller's context may carry a narrow
# precision or an enabled Inexact trap, either of which would reject a score
# the domain accepts.
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


def _require_decimal_score(score: object) -> None:
    """Require a finite decimal.Decimal score."""
    if not isinstance(score, decimal.Decimal):
        msg = "rubric_score must be a decimal.Decimal."
        raise TypeError(msg)
    if not score.is_finite():
        # A non-finite score has no ordering against the unit-interval bounds:
        # comparing NaN signals InvalidOperation rather than answering the
        # question, so reject it here with a message that names the cause.
        msg = "rubric_score must be a finite decimal."
        raise ValueError(msg)
    if not _RUBRIC_LOW <= score <= _RUBRIC_HIGH:
        # Anything outside this window cannot round into the stored unit
        # interval, so reject it before quantizing.
        msg = "rubric_score must lie within the accepted rounding window."
        raise ValueError(msg)


def _rounded_unit_score(score: decimal.Decimal) -> decimal.Decimal:
    """Round *score* half-to-even at the domain's four-decimal precision."""
    try:
        with decimal.localcontext(_QUANTIZE_CONTEXT):
            return score.quantize(
                _RUBRIC_QUANTUM,
                rounding=decimal.ROUND_HALF_EVEN,
            )
    except decimal.InvalidOperation as exc:
        msg = "rubric_score must be representable at four decimal places."
        raise ValueError(msg) from exc


def _require_unit_interval(rounded: decimal.Decimal) -> None:
    """Require *rounded* to lie within the unit interval."""
    if rounded < 0 or rounded > 1:
        msg = (
            "rubric_score must lie within [0, 1] after rounding to four decimal places."
        )
        raise ValueError(msg)


def _normalize_rubric_score(
    score: decimal.Decimal | None,
) -> decimal.Decimal | None:
    """Return *score* at the stored precision, rejecting unusable values.

    pre: score is None or (score.is_finite() and _RUBRIC_LOW <= score <= _RUBRIC_HIGH)
    post: (score is None) == (__return__ is None)
    post: __return__ is None or 0 <= __return__ <= 1
    post: __return__ is None or abs(__return__ - score) <= _RUBRIC_TOLERANCE

    Returns
    -------
    decimal.Decimal | None
        ``None`` when *score* is ``None``, otherwise the score rounded to four
        decimal places with any negative zero replaced by zero.
    """
    if score is None:
        return None
    _require_decimal_score(score)
    rounded = _rounded_unit_score(score)
    _require_unit_interval(rounded)
    # A rounded negative zero compares equal to zero but serializes as -0.0.
    return rounded.copy_abs() if rounded.is_zero() else rounded
