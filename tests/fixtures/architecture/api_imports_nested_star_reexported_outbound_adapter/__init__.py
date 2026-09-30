"""Fixture package that star-re-exports an outbound adapter."""

from .barrel import *  # ruff: ignore[undefined-local-with-import-star]  # The fixture deliberately exercises architecture analysis of star re-exports.
