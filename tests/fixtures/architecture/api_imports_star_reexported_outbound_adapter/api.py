"""Violating inbound adapter that star-imports a re-exported outbound adapter."""

from . import *  # noqa: F403

ADAPTER = StorageAdapter()  # noqa: F405
