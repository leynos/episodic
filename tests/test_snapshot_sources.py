"""Tests for snapshotting resolved reference bindings into source documents."""

import datetime as dt
import typing as typ

import pytest

from episodic.canonical.reference_documents import resolve_bindings
from episodic.canonical.reference_documents.snapshots import (
    SnapshotContext,
    snapshot_resolved_bindings,
)

if typ.TYPE_CHECKING:
    from episodic.canonical.domain import (
        CanonicalEpisode,
        IngestionJob,
        ReferenceBinding,
        ReferenceDocument,
        ReferenceDocumentRevision,
        SeriesProfile,
    )
    from episodic.canonical.ports import CanonicalUnitOfWork

pytestmark = pytest.mark.asyncio


async def test_snapshot_resolved_bindings_persists_reference_source_documents(
    binding_test_uow: CanonicalUnitOfWork,
    binding_test_episode: CanonicalEpisode,
    binding_test_document: ReferenceDocument,
    binding_test_revision_v1: ReferenceDocumentRevision,
    binding_test_series: SeriesProfile,
    binding_snapshot_job: IngestionJob,
    binding_snapshot_reference_binding: ReferenceBinding,
) -> None:
    """Resolved bindings should be persisted as provenance source documents."""
    resolved = await resolve_bindings(
        binding_test_uow,
        series_profile_id=binding_test_series.id,
        episode_id=binding_test_episode.id,
    )
    snapshot_created_at = dt.datetime(2026, 4, 2, 12, 0, tzinfo=dt.UTC)

    created_documents = await snapshot_resolved_bindings(
        binding_test_uow,
        resolved=resolved,
        context=SnapshotContext(
            ingestion_job_id=binding_snapshot_job.id,
            canonical_episode_id=binding_test_episode.id,
            created_at=snapshot_created_at,
        ),
    )

    assert len(created_documents) == 1
    created = created_documents[0]
    assert created.source_type == "reference_document"
    assert created.reference_document_revision_id == binding_test_revision_v1.id
    assert created.canonical_episode_id == binding_test_episode.id
    assert created.source_uri == (
        f"ref://{binding_test_document.id}/revisions/{binding_test_revision_v1.id}"
    )
    assert created.metadata["binding_id"] == str(binding_snapshot_reference_binding.id)
    assert created.metadata["document_kind"] == binding_test_document.kind.value
    assert created.created_at == snapshot_created_at

    await binding_test_uow.commit()

    persisted = await binding_test_uow.source_documents.list_for_job(
        binding_snapshot_job.id
    )
    assert len(persisted) == 1
    assert persisted[0].reference_document_revision_id == binding_test_revision_v1.id
    assert persisted[0].created_at == snapshot_created_at
