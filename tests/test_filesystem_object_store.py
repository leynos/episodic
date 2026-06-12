"""Tests for the filesystem source-intake object-store adapter."""

import asyncio
import hashlib
import typing as typ

import pytest

from episodic.canonical.object_store import (
    InvalidObjectKeyError,
    PayloadTooLargeError,
)
from episodic.canonical.storage.filesystem_object_store import FilesystemObjectStore

if typ.TYPE_CHECKING:
    import collections.abc as cabc
    import pathlib


async def _byte_stream(*chunks: bytes) -> cabc.AsyncIterator[bytes]:
    """Yield byte chunks for object-store tests."""
    for chunk in chunks:
        await _checkpoint()
        yield chunk


async def _checkpoint() -> None:
    """Give async tests a real scheduling point."""
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_filesystem_object_store_round_trips_chunks(
    tmp_path: pathlib.Path,
) -> None:
    """Stored objects should report size/hash and read back the same bytes."""
    store = FilesystemObjectStore(tmp_path)

    stored = await store.put(
        "uploads/example.bin",
        _byte_stream(b"hello", b"\n"),
        max_bytes=6,
    )

    assert stored.key == "uploads/example.bin"
    assert stored.size == 6
    assert stored.sha256 == (
        "5891b5b522d5df086d0ff0b110fbd9d21bb4fc7163af34d08286a2e846f6be03"
    )
    async with store.open(stored.key) as chunks:
        assert b"".join([chunk async for chunk in chunks]) == b"hello\n"


@pytest.mark.asyncio
async def test_filesystem_object_store_uses_precomputed_sha256(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A supplied digest should be trusted while size and bytes are still stored."""
    store = FilesystemObjectStore(tmp_path)
    supplied_digest = "f" * 64

    def fail_hashing() -> typ.NoReturn:
        raise AssertionError

    monkeypatch.setattr(hashlib, "sha256", fail_hashing)

    stored = await store.put(
        "uploads/precomputed.bin",
        _byte_stream(b"hello", b"\n"),
        max_bytes=6,
        precomputed_sha256=supplied_digest,
    )

    assert stored.key == "uploads/precomputed.bin"
    assert stored.size == 6
    assert stored.sha256 == supplied_digest
    async with store.open(stored.key) as chunks:
        assert b"".join([chunk async for chunk in chunks]) == b"hello\n"


@pytest.mark.asyncio
async def test_filesystem_object_store_rejects_path_traversal(
    tmp_path: pathlib.Path,
) -> None:
    """Object keys must stay relative to the configured root."""
    store = FilesystemObjectStore(tmp_path)

    with pytest.raises(InvalidObjectKeyError):
        await store.put("../escape.bin", _byte_stream(b"nope"), max_bytes=10)


@pytest.mark.asyncio
async def test_filesystem_object_store_rejects_oversized_payload(
    tmp_path: pathlib.Path,
) -> None:
    """PayloadTooLargeError should leave no target object behind."""
    store = FilesystemObjectStore(tmp_path)

    with pytest.raises(PayloadTooLargeError):
        await store.put("uploads/too-large.bin", _byte_stream(b"abcdef"), max_bytes=5)

    assert not (tmp_path / "uploads" / "too-large.bin").exists()
