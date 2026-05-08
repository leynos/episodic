"""Violating inbound adapter that imports a re-exported outbound adapter."""

from tests.fixtures.architecture.api_imports_reexported_outbound_adapter import (
    StorageAdapter,
)

ADAPTER = StorageAdapter()
