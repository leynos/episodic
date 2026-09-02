"""Provide cache support types and atomic writes for the spelling helper."""

import collections.abc as cabc
import dataclasses as dc
import os
import pathlib
import tempfile
import typing as typ


@dc.dataclass(frozen=True)
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


@dc.dataclass(frozen=True)
class AtomicWriteOptions:
    """Configure atomic replacement behaviour."""

    create_parents: bool = True
    preserve_mode: bool = False
    sync_file: bool = False


def atomic_write(
    path: pathlib.Path,
    content: bytes,
    *,
    options: AtomicWriteOptions = AtomicWriteOptions(),
) -> None:
    """Atomically replace a path after writing a temporary sibling.

    Parameters
    ----------
    path : pathlib.Path
        Destination to replace.
    content : bytes
        Complete replacement contents.
    options : AtomicWriteOptions
        Directory creation, mode preservation, and fsync policy. The default
        creates missing parents, ignores the destination mode, and does not
        fsync.
    """
    if options.create_parents:
        path.parent.mkdir(parents=True, exist_ok=True)
    mode = path.stat().st_mode if options.preserve_mode else None
    with tempfile.NamedTemporaryFile(
        delete=False, dir=path.parent, prefix=f".{path.name}."
    ) as stream:
        stream.write(content)
        stream.flush()
        if options.sync_file:
            os.fsync(stream.fileno())
        temporary = pathlib.Path(stream.name)
    try:
        if mode is not None:
            temporary.chmod(mode)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
