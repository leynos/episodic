"""Star-only barrel that forwards public storage exports."""

from .storage import *  # ruff: ignore[undefined-local-with-import-star]  # The fixture deliberately exercises architecture analysis of star re-exports.
