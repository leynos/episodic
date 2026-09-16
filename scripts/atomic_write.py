"""Replace files atomically through a temporary sibling.

A neutral persistence helper shared by the spelling-cache rollout and the
duplication allowlist writer. It belongs to neither caller's domain: both need
the same write-temporary-then-``Path.replace`` sequence with the same knobs,
so the routine lives on its own rather than in whichever module needed it
first.
"""

import collections.abc as cabc
import contextlib
import dataclasses as dc
import os
import pathlib
import tempfile


@dc.dataclass(frozen=True, slots=True)
class AtomicWriteOptions:
    """Configure atomic replacement behaviour."""

    create_parents: bool = True
    preserve_mode: bool = False
    sync_file: bool = False


@contextlib.contextmanager
def _open_directory(directory: pathlib.Path) -> cabc.Iterator[int]:
    """Open a directory descriptor for a scoped operation.

    Reading a directory needs O_RDONLY, which is not portable to Python's
    buffered ``open``; the raw descriptor is yielded so the caller's work runs
    between the open and the guaranteed close. A failure in ``os.open`` itself
    leaves no descriptor to release.

    Yields
    ------
    int
        The open directory descriptor.
    """
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        yield descriptor
    finally:
        os.close(descriptor)


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
    mode = path.stat().st_mode if options.preserve_mode and path.exists() else None
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
        if options.sync_file:
            with _open_directory(path.parent) as descriptor:
                os.fsync(descriptor)
    finally:
        temporary.unlink(missing_ok=True)
