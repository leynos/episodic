"""Violating inbound adapter that star-imports a re-exported outbound adapter."""

from . import *  # noqa: F403  # Fixture requires star-imported re-exports.

ADAPTER = StorageAdapter()  # noqa: F405  # The fixture deliberately exercises architecture analysis of star re-exports.
