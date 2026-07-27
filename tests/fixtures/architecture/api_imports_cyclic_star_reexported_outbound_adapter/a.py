"""Cyclic star barrel that also exposes a concrete outbound adapter."""

from .b import *  # noqa: F403  # The fixture deliberately exercises architecture analysis of star re-exports.
from .storage import (
    StorageAdapter,  # noqa: F401  # The imported adapter is deliberately re-exported by this architecture fixture.
)
