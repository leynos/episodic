"""Shared coercion helpers for canonical adapter configuration values."""

from __future__ import annotations

_COERCE_FLOAT_ERRORS = (TypeError, ValueError)


def coerce_float(value: object, default: float) -> float:
    """Coerce ``value`` to ``float`` and return ``default`` on failure.

    Parameters
    ----------
    value : object
        Candidate value to convert to ``float``. Only ``int``, ``float``, and
        ``str`` values are conversion candidates; all other input types
        immediately use ``default``.
    default : float
        Fallback value returned when conversion is not possible.

    Returns
    -------
    float
        Converted floating-point value when conversion succeeds; otherwise
        ``default``. Conversion errors are caught and are not propagated.
    """
    if not isinstance(value, (int, float, str)):
        return default
    try:
        return float(value)
    except _COERCE_FLOAT_ERRORS:
        return default
