"""Fixture package that star-re-exports through a cyclic barrel."""

from .b import *  # ruff: ignore[undefined-local-with-import-star]  # The fixture deliberately exercises architecture analysis of star re-exports.
