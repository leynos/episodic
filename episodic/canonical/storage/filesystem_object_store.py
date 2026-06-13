"""Filesystem-backed object store for source-intake uploads."""

import asyncio
import contextlib
import hashlib
import typing as typ
import uuid

from episodic.canonical.object_store import (
    ObjectStorePort,
    PayloadTooLargeError,
    StoredObject,
    validate_object_key,
)

_OBJECT_STORE_READ_CHUNK_BYTES = 64 * 1024

if typ.TYPE_CHECKING:
    import collections.abc as cabc
    import pathlib


class _HashDigest(typ.Protocol):
    """Small structural type for hash objects used while writing streams."""

    def update(self, data: bytes, /) -> None:
        """Update the hash with one byte chunk."""
        raise NotImplementedError

    def hexdigest(self) -> str:
        """Return the hex digest."""
        raise NotImplementedError


async def _write_stream_to_file(
    file_handle: typ.IO[bytes],
    stream: cabc.AsyncIterator[bytes],
    *,
    max_bytes: int,
    digest: _HashDigest | None,
) -> int:
    """Write stream chunks to an open file handle; return the total byte count.

    Raises PayloadTooLargeError if accumulated size exceeds max_bytes.
    Updates digest in place when supplied.
    """
    size = 0
    async for chunk in stream:
        next_size = size + len(chunk)
        if next_size > max_bytes:
            _raise_payload_too_large()
        file_handle.write(chunk)
        if digest is not None:
            digest.update(chunk)
        size = next_size
    return size


def _resolve_sha256(
    digest: _HashDigest | None,
    precomputed_sha256: str | None,
) -> str:
    """Return the hex SHA-256 string from either digest source."""
    if digest is None:
        if precomputed_sha256 is None:
            msg = "digest and precomputed_sha256 cannot both be None"
            raise AssertionError(msg)
        return precomputed_sha256
    return digest.hexdigest()


class FilesystemObjectStore(ObjectStorePort):
    """Store object bytes under a configured filesystem root."""

    def __init__(self, root: pathlib.Path) -> None:
        self._root = root
        self._tmp_root = root / "_tmp"

    # pylint: disable-next=too-many-arguments
    async def put(
        self,
        key: str,
        stream: cabc.AsyncIterator[bytes],
        *,
        max_bytes: int,
        precomputed_sha256: str | None = None,
    ) -> StoredObject:
        """Store stream bytes atomically and return observed size/hash."""
        if max_bytes < 0:
            msg = "max_bytes must be non-negative."
            raise ValueError(msg)
        safe_key = validate_object_key(key)
        target = self._resolve_under_root(safe_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        self._tmp_root.mkdir(parents=True, exist_ok=True)
        tmp_path = self._tmp_root / f"{uuid.uuid4()}.tmp"

        digest = None if precomputed_sha256 is not None else hashlib.sha256()
        try:
            with tmp_path.open("wb") as file_handle:
                size = await _write_stream_to_file(
                    file_handle, stream, max_bytes=max_bytes, digest=digest
                )
            tmp_path.replace(target)
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise

        sha256_result = _resolve_sha256(digest, precomputed_sha256)
        return StoredObject(key=safe_key, size=size, sha256=sha256_result)

    @contextlib.asynccontextmanager
    async def open(self, key: str) -> cabc.AsyncIterator[cabc.AsyncIterator[bytes]]:
        """Yield an async iterator over stored bytes."""
        path = self._resolve_under_root(validate_object_key(key))

        async def _chunks() -> cabc.AsyncIterator[bytes]:
            with path.open("rb") as file_handle:
                while chunk := file_handle.read(_OBJECT_STORE_READ_CHUNK_BYTES):
                    await _yield_checkpoint()
                    yield chunk

        yield _chunks()

    async def delete(self, key: str) -> None:
        """Delete stored bytes if they exist."""
        self._resolve_under_root(validate_object_key(key)).unlink(missing_ok=True)

    def _resolve_under_root(self, key: str) -> pathlib.Path:
        """Return a root-confined path for a validated key."""
        root = self._root.resolve()
        candidate = (root / key).resolve(strict=False)
        if not candidate.is_relative_to(root):
            msg = "object key escapes object store root."
            raise ValueError(msg)
        return candidate


async def _yield_checkpoint() -> None:
    """Keep object reads cooperative without adding an I/O dependency."""
    await asyncio.sleep(0)


def _raise_payload_too_large() -> typ.NoReturn:
    """Raise the canonical payload-size exception."""
    raise PayloadTooLargeError
