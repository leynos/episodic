"""Unit tests for source-intake application services."""

from __future__ import annotations

import hashlib
import typing as typ

import pytest
import sqlalchemy as sa

from episodic.canonical.source_intake_service import (
    UploadBytesRequest,
    UploadHashMismatchError,
    _validate_declared_upload,
    register_upload,
)
from episodic.canonical.storage import FilesystemObjectStore, SqlAlchemyUnitOfWork
from episodic.canonical.storage.source_intake_models import UploadRecord
from episodic.canonical.uploads import UploadState

if typ.TYPE_CHECKING:
    import collections.abc as cabc
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class _SecondCommitFailsUnitOfWork(SqlAlchemyUnitOfWork):
    """Fail the second commit issued by a shared factory."""

    def __init__(
        self,
        session_factory: cabc.Callable[[], AsyncSession],
        counter: list[int],
    ) -> None:
        super().__init__(session_factory)
        self._counter = counter

    @typ.override
    async def commit(self) -> None:
        """Raise before the second transaction commits."""
        self._counter[0] += 1
        if self._counter[0] == 2:
            msg = "simulated ready commit failure"
            raise RuntimeError(msg)
        await super().commit()


@pytest.mark.asyncio
async def test_register_upload_keeps_pending_row_when_ready_commit_fails(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """A failed ready commit leaves the pending upload row recoverable."""
    commit_counter = [0]
    object_store = FilesystemObjectStore(tmp_path / "objects")
    payload = b"recoverable upload\n"

    def failing_uow_factory() -> _SecondCommitFailsUnitOfWork:
        return _SecondCommitFailsUnitOfWork(session_factory, commit_counter)

    with pytest.raises(RuntimeError, match="simulated ready commit failure"):
        await register_upload(
            failing_uow_factory,
            object_store,
            UploadBytesRequest(
                owner_principal_id="principal",
                content_type="text/plain",
                declared_size=len(payload),
                declared_sha256=None,
                payload=payload,
                max_bytes=1024,
                metadata={"language": "en"},
            ),
        )
    assert commit_counter[0] == 2, "expected pending and ready commits to run"

    async with session_factory() as session:
        records = (await session.scalars(sa.select(UploadRecord))).all()

    assert len(records) == 1, "expected one recoverable upload row"
    record = records[0]
    assert record.state is UploadState.PENDING, "expected upload to remain pending"
    assert record.actual_size is None, "expected actual_size to stay unset"
    assert record.content_hash is None, "expected content_hash to stay unset"
    async with object_store.open(record.storage_key) as chunks:
        stored_payload = b"".join([chunk async for chunk in chunks])
    assert stored_payload == payload, "expected object-store payload to match input"


@pytest.mark.asyncio
async def test_register_upload_recomputes_untrusted_payload_hash(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """A caller-supplied payload digest cannot override the uploaded bytes."""
    payload = b"trusted bytes\n"
    object_store = FilesystemObjectStore(tmp_path / "objects")

    upload = await register_upload(
        lambda: SqlAlchemyUnitOfWork(session_factory),
        object_store,
        UploadBytesRequest(
            owner_principal_id="principal",
            content_type="text/plain",
            declared_size=len(payload),
            declared_sha256=None,
            payload=payload,
            max_bytes=1024,
            metadata={"language": "en"},
            payload_sha256="bad",
        ),
    )

    assert upload.content_hash == f"sha256:{hashlib.sha256(payload).hexdigest()}"


def test_validate_declared_upload_uses_precomputed_hash() -> None:
    """Declared hash validation compares against the supplied payload digest."""
    request = UploadBytesRequest(
        owner_principal_id="principal",
        content_type="text/plain",
        declared_size=6,
        declared_sha256="declared-digest",
        payload=b"upload",
        max_bytes=1024,
        metadata={},
        payload_sha256="precomputed-digest",
    )

    with pytest.raises(UploadHashMismatchError):
        _validate_declared_upload(request)
