"""Provide cache support types for the spelling helper.

The atomic-write routine these types drive lives in
:mod:`atomic_write` and is re-exported here so existing importers keep
working.
"""

import collections.abc as cabc
import dataclasses as dc
import pathlib
import typing as typ

from atomic_write import AtomicWriteOptions, atomic_write

__all__ = [
    "AtomicWriteOptions",
    "CacheTargets",
    "RefreshResult",
    "RemoteResponse",
    "atomic_write",
]


@dc.dataclass(frozen=True, slots=True)
class RefreshResult:
    """Describe whether the untracked shared dictionary cache changed."""

    status: str
    cache: pathlib.Path


@dc.dataclass(frozen=True)
class CacheTargets:
    """Group the untracked dictionary cache and metadata sidecar paths."""

    cache: pathlib.Path
    metadata: pathlib.Path


class RemoteResponse(typ.Protocol):
    """Expose the HTTP response surface used by cache refresh."""

    status: int
    headers: cabc.Mapping[str, str]

    def read(self) -> bytes:
        """Read the response body."""
        ...
