"""Violating inbound adapter that imports a star-re-exported outbound adapter."""

from . import StorageAdapter

ADAPTER = StorageAdapter()
