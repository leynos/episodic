"""Tests for bounded source hydration before draft generation."""

import asyncio
import contextlib
import dataclasses as dc
import datetime as dt
import typing as typ
import uuid

import pytest

from episodic.canonical.domain import SourceDocument
from episodic.canonical.storage.filesystem_object_store import FilesystemObjectStore
from episodic.generation.draft_script import DraftScriptGenerationError
from episodic.generation.launcher import InProcessGenerationRunLauncher
from episodic.generation.launcher_support import (
    GenerationSourceLimitError,
    GenerationSourceLimits,
    source_from_document,
)
from tests.generation_run_launcher_support import RecordingDraftGenerator, draft_result

if typ.TYPE_CHECKING:
    import collections.abc as cabc
    from pathlib import Path

    from episodic.canonical.object_store import ObjectStorePort
    from episodic.canonical.unit_of_work_protocols import CanonicalUnitOfWork


@dc.dataclass(slots=True)
class _ChunkStore:
    """Object-store fake that records how many source chunks were consumed."""

    chunks: tuple[bytes, ...]
    yielded_chunks: int = 0

    @contextlib.asynccontextmanager
    async def open(
        self,
        key: str,
    ) -> cabc.AsyncIterator[cabc.AsyncIterator[bytes]]:
        """Yield the configured source bytes without retaining additional data."""
        del key

        async def iterator() -> cabc.AsyncIterator[bytes]:
            """Yield one configured chunk at a time."""
            for chunk in self.chunks:
                self.yielded_chunks += 1
                await asyncio.sleep(0)
                yield chunk

        yield iterator()


def _source_document(
    *, content: str | None = None, source_uri: str = "source"
) -> SourceDocument:
    """Return one canonical source document with optional inline content."""
    return SourceDocument(
        id=uuid.uuid7(),
        ingestion_job_id=uuid.uuid7(),
        canonical_episode_id=uuid.uuid7(),
        reference_document_revision_id=None,
        source_type="research_note",
        source_uri=source_uri,
        weight=1.0,
        content_hash="sha256:source",
        metadata={} if content is None else {"content": content},
        created_at=dt.datetime(2026, 8, 20, tzinfo=dt.UTC),
    )


def _launcher(*, limits: GenerationSourceLimits) -> InProcessGenerationRunLauncher:
    """Build a launcher only for its source-loading boundary."""
    return InProcessGenerationRunLauncher(
        uow_factory=lambda: typ.cast("CanonicalUnitOfWork", object()),
        draft_generator=RecordingDraftGenerator(draft_result("<TEI/>")),
        source_limits=limits,
    )


@pytest.mark.asyncio
async def test_source_loading_rejects_count_above_configured_limit() -> None:
    """Reject source bundles before loading content beyond the source-count bound."""
    run_launcher = _launcher(
        limits=GenerationSourceLimits(
            max_source_count=1,
            max_source_bytes=10,
            max_aggregate_source_bytes=10,
            max_normalized_source_bytes=10,
        )
    )

    with pytest.raises(GenerationSourceLimitError, match="count"):
        await run_launcher._load_sources([
            _source_document(content="one"),
            _source_document(content="two"),
        ])


@pytest.mark.asyncio
async def test_uploaded_source_stops_before_retaining_over_limit_chunk() -> None:
    """Stop streaming when the next uploaded chunk exceeds the source limit."""
    store = _ChunkStore((b"1234", b"5678", b"not-read"))
    limits = GenerationSourceLimits(
        max_source_count=2,
        max_source_bytes=6,
        max_aggregate_source_bytes=10,
        max_normalized_source_bytes=10,
    )

    with pytest.raises(GenerationSourceLimitError, match="source exceeds byte"):
        await source_from_document(
            _source_document(source_uri="upload:uploads/source"),
            typ.cast("ObjectStorePort", store),
            limits,
        )

    assert store.yielded_chunks == 2, store.yielded_chunks


@pytest.mark.asyncio
async def test_uploaded_source_rejects_invalid_utf8() -> None:
    """Report invalid upload text with the stable source-key diagnostic."""
    with pytest.raises(DraftScriptGenerationError) as raised:
        await source_from_document(
            _source_document(source_uri="upload:uploads/source"),
            typ.cast("ObjectStorePort", _ChunkStore((b"\xff",))),
        )
    assert (
        str(raised.value) == "Uploaded source 'uploads/source' is not valid UTF-8 text."
    ), (
        "expected invalid UTF-8 diagnostic for 'uploads/source', "
        f"got {str(raised.value)!r}"
    )


@pytest.mark.asyncio
async def test_uploaded_source_rejects_whitespace_only_text() -> None:
    """Report whitespace-only upload text with the stable source-key diagnostic."""
    with pytest.raises(DraftScriptGenerationError) as raised:
        await source_from_document(
            _source_document(source_uri="upload:uploads/source"),
            typ.cast("ObjectStorePort", _ChunkStore((b" \n\t ",))),
        )
    assert str(raised.value) == "Uploaded source 'uploads/source' contains no text.", (
        "expected empty-text diagnostic for 'uploads/source', "
        f"got {str(raised.value)!r}"
    )


@pytest.mark.asyncio
async def test_source_loading_enforces_aggregate_and_normalized_limits() -> None:
    """Distinguish aggregate input capacity from normalized-text capacity."""
    aggregate_limits = GenerationSourceLimits(
        max_source_count=2,
        max_source_bytes=10,
        max_aggregate_source_bytes=4,
        max_normalized_source_bytes=10,
    )
    normalized_limits = GenerationSourceLimits(
        max_source_count=2,
        max_source_bytes=10,
        max_aggregate_source_bytes=10,
        max_normalized_source_bytes=4,
    )

    with pytest.raises(GenerationSourceLimitError, match="aggregate"):
        await source_from_document(
            _source_document(content="12345"),
            None,
            aggregate_limits,
            remaining_aggregate_bytes=4,
        )
    with pytest.raises(GenerationSourceLimitError, match="normalized"):
        await source_from_document(
            _source_document(content="12345"),
            None,
            normalized_limits,
        )


@pytest.mark.asyncio
async def test_filesystem_object_store_offloads_open_read_and_close(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Perform filesystem reads through threads rather than the event loop."""
    import episodic.canonical.storage.filesystem_object_store as object_store_module

    store = FilesystemObjectStore(tmp_path)
    path = tmp_path / "uploads" / "source"
    path.parent.mkdir()
    path.write_bytes(b"source")
    offloaded: list[str] = []
    original_to_thread = object_store_module.asyncio.to_thread

    async def recording_to_thread(
        function: cabc.Callable[..., object],
        /,
        *args: object,
        **kwargs: object,
    ) -> object:
        """Record the blocking operation delegated by the storage adapter."""
        offloaded.append(getattr(function, "__name__", type(function).__name__))
        return await original_to_thread(function, *args, **kwargs)

    monkeypatch.setattr(object_store_module.asyncio, "to_thread", recording_to_thread)
    async with store.open("uploads/source") as chunks:
        content = b"".join([chunk async for chunk in chunks])

    assert content == b"source", f"expected stored source bytes, got {content!r}"
    assert offloaded == ["open", "read", "read", "close"], offloaded
