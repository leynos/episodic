"""Violating inbound adapter that star-imports a re-exported outbound adapter."""

from tests.fixtures.architecture.api_imports_star_reexported_outbound_adapter import *  # noqa: F403

ADAPTER = StorageAdapter()  # noqa: F405
