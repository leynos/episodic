"""Violating inbound adapter that star-imports a re-exported outbound adapter."""

from . import *  # ruff: ignore[undefined-local-with-import-star]  # Fixture requires star-imported re-exports.

ADAPTER = StorageAdapter()  # ruff: ignore[undefined-local-with-import-star-usage]  # The fixture deliberately exercises architecture analysis of star re-exports.
