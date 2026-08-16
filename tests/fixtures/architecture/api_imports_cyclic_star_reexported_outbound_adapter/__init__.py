"""Fixture package that star-re-exports through a cyclic barrel."""

from .b import *  # noqa: F403  # The fixture deliberately exercises architecture analysis of star re-exports.
