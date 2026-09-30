"""Cyclic star barrel that also exposes a concrete outbound adapter."""

from .b import *  # ruff: ignore[undefined-local-with-import-star]  # The fixture deliberately exercises architecture analysis of star re-exports.
from .storage import (
    StorageAdapter,  # ruff: ignore[unused-import]  # The imported adapter is deliberately re-exported by this architecture fixture.
)
