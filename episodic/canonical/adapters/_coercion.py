"""Shared coercion helpers for canonical adapter configuration values."""

from __future__ import annotations


def coerce_float(value: object, default: float) -> float:
    """Coerce ``value`` to ``float`` and return ``default`` on failure."""
    if not isinstance(value, (int, float, str)):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
