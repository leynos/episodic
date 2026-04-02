"""Tests for snapshotting resolved reference bindings into source documents."""

import datetime as dt
import typing as typ

import pytest

import episodic.canonical.reference_documents.snapshots as snapshot_module
from episodic.canonical.reference_documents import resolve_bindings
from episodic.canonical.reference_documents.snapshots import (
    SnapshotContext,
    snapshot_resolved_bindings,
)

if typ.TYPE_CHECKING:
    from tests.conftest import _SnapshotTestFixtures

pytestmark = pytest.mark.asyncio


async def test_snapshot_resolved_bindings_persists_reference_source_documents(
    binding_snapshot_fixtures: _SnapshotTestFixtures,
) -> None:
    """Resolved bindings should be persisted as provenance source documents."""
    fx = binding_snapshot_fixtures
    resolved = await resolve_bindings(
        fx.uow,
        series_profile_id=fx.series.id,
        episode_id=fx.episode.id,
    )
    snapshot_created_at = dt.datetime(2026, 4, 2, 12, 0, tzinfo=dt.UTC)

    created_documents = await snapshot_resolved_bindings(
        fx.uow,
        resolved=resolved,
        context=SnapshotContext(
            ingestion_job_id=fx.job.id,
            canonical_episode_id=fx.episode.id,
            created_at=snapshot_created_at,
        ),
    )

    assert len(created_documents) == 1
    created = created_documents[0]
    assert created.source_type == "reference_document"
    assert created.reference_document_revision_id == fx.revision_v1.id
    assert created.canonical_episode_id == fx.episode.id
    assert created.source_uri == (
        f"ref://{fx.document.id}/revisions/{fx.revision_v1.id}"
    )
    assert created.metadata["binding_id"] == str(fx.reference_binding.id)
    assert created.metadata["document_kind"] == fx.document.kind.value
    assert created.created_at == snapshot_created_at

    await fx.uow.commit()

    persisted = await fx.uow.source_documents.list_for_job(fx.job.id)
    assert len(persisted) == 1
    assert persisted[0].reference_document_revision_id == fx.revision_v1.id
    assert persisted[0].created_at == snapshot_created_at


async def test_snapshot_resolved_bindings_defaults_created_at_to_current_time(
    binding_snapshot_fixtures: _SnapshotTestFixtures,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Snapshotting without a timestamp should fall back to the current UTC time."""
    fx = binding_snapshot_fixtures
    resolved = await resolve_bindings(
        fx.uow,
        series_profile_id=fx.series.id,
        episode_id=fx.episode.id,
    )
    fallback_created_at = dt.datetime(2026, 4, 2, 13, 0, tzinfo=dt.UTC)
    real_datetime = snapshot_module.dt.datetime

    class _FixedDateTime(dt.datetime):
        @classmethod
        def now(
            cls,
            tz: dt.tzinfo | None = None,
        ) -> dt.datetime:
            assert tz == dt.UTC
            return fallback_created_at

    monkeypatch.setattr(snapshot_module.dt, "datetime", _FixedDateTime)
    try:
        created_documents = await snapshot_resolved_bindings(
            fx.uow,
            resolved=resolved,
            context=SnapshotContext(
                ingestion_job_id=fx.job.id,
                canonical_episode_id=fx.episode.id,
                created_at=None,
            ),
        )
    finally:
        monkeypatch.setattr(snapshot_module.dt, "datetime", real_datetime)

    assert len(created_documents) == 1
    created = created_documents[0]
    assert created.source_type == "reference_document"
    assert created.reference_document_revision_id == fx.revision_v1.id
    assert created.canonical_episode_id == fx.episode.id
    assert created.source_uri == (
        f"ref://{fx.document.id}/revisions/{fx.revision_v1.id}"
    )
    assert created.metadata["binding_id"] == str(fx.reference_binding.id)
    assert created.metadata["document_kind"] == fx.document.kind.value
    assert created.created_at == fallback_created_at

    await fx.uow.commit()

    persisted = await fx.uow.source_documents.list_for_job(fx.job.id)
    assert len(persisted) == 1
    assert persisted[0].reference_document_revision_id == fx.revision_v1.id
    assert persisted[0].created_at == fallback_created_at
