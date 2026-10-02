"""Cyclic star barrel that forwards exports from module a."""

from .a import *  # ruff: ignore[undefined-local-with-import-star]  # The fixture deliberately exercises architecture analysis of star re-exports.
