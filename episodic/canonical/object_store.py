"""Object-storage port for source-intake upload bytes."""

import dataclasses as dc
import pathlib
import typing as typ

if typ.TYPE_CHECKING:
    import collections.abc as cabc
    import contextlib


@dc.dataclass(frozen=True, slots=True)
class StoredObject:
    """Result returned after bytes are stored."""

    key: str
    size: int
    sha256: str


class ObjectStoreError(RuntimeError):
    """Base error for object-store boundary failures."""


class InvalidObjectKeyError(ObjectStoreError, ValueError):
    """Raised when an object key can escape the object-store namespace."""


class PayloadTooLargeError(ObjectStoreError):
    """Raised when a byte stream exceeds the configured maximum size."""


def validate_object_key(key: str) -> str:
    """Validate and return a relative object-store key."""
    path = pathlib.PurePosixPath(key)
    if not key.strip() or _has_unsafe_object_key_parts(key, path):
        msg = "object store keys must be non-empty relative POSIX paths."
        raise InvalidObjectKeyError(msg)
    return key


def _has_unsafe_object_key_parts(key: str, path: pathlib.PurePosixPath) -> bool:
    """Return True when a key can escape or confuse the object namespace."""
    forbidden_parts = {"", ".", ".."}
    return (
        path.is_absolute()
        or "\\" in key
        or any(part in forbidden_parts for part in path.parts)
    )


class ObjectStorePort(typ.Protocol):
    """Driven port for storing and retrieving opaque byte streams."""

    async def put(
        self,
        key: str,
        stream: cabc.AsyncIterator[bytes],
        *,
        max_bytes: int,
    ) -> StoredObject:
        """Store stream bytes under key and return size/hash metadata."""
        raise NotImplementedError

    def open(
        self, key: str
    ) -> contextlib.AbstractAsyncContextManager[cabc.AsyncIterator[bytes]]:
        """Open stored bytes as an async iterator."""
        raise NotImplementedError

    async def delete(self, key: str) -> None:
        """Delete stored bytes if present."""
        raise NotImplementedError
