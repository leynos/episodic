"""Canonical seed fixtures shared by generation-run launcher tests.

These builders persist the series profile, ingestion job, source attachment,
and presenter bindings that a generation run needs, plus the frozen clock the
launcher fixtures use. They live apart from the launcher construction helpers
so each module stays inside the 400-line limit.
"""

import datetime as dt
import uuid

from episodic.canonical.domain import (
    IngestionJob,
    IngestionStatus,
    IntakeState,
    ReferenceBinding,
    ReferenceBindingTargetKind,
    ReferenceDocument,
    ReferenceDocumentKind,
    ReferenceDocumentLifecycleState,
    ReferenceDocumentRevision,
    SeriesProfile,
)
from episodic.canonical.ingestion_sources import AttachmentKind, IngestionJobSource

NOW = dt.datetime(2026, 6, 24, 12, 0, tzinfo=dt.UTC)


def _clock() -> dt.datetime:
    """Return the frozen launcher timestamp."""
    return NOW


def _series_profile() -> SeriesProfile:
    """Return a series profile fixture."""
    return SeriesProfile(
        id=uuid.UUID("00000000-0000-0000-0000-000000000201"),
        slug="bridgewater",
        title="Bridgewater",
        description=None,
        configuration={},
        guardrails={},
        created_at=NOW,
        updated_at=NOW,
    )


def _ingestion_job(series_profile_id: uuid.UUID) -> IngestionJob:
    """Return a ready intake job fixture."""
    return IngestionJob(
        id=uuid.UUID("00000000-0000-0000-0000-000000000301"),
        series_profile_id=series_profile_id,
        target_episode_id=None,
        status=IngestionStatus.PENDING,
        requested_at=NOW,
        started_at=None,
        completed_at=None,
        error_message=None,
        created_at=NOW,
        updated_at=NOW,
        intake_state=IntakeState.READY_FOR_GENERATION,
    )


def _source(job_id: uuid.UUID) -> IngestionJobSource:
    """Return one source attachment carrying text for generation."""
    return IngestionJobSource(
        id=uuid.UUID("00000000-0000-0000-0000-000000000401"),
        ingestion_job_id=job_id,
        attachment_kind=AttachmentKind.SOURCE_URI,
        upload_id=None,
        source_uri="https://example.test/source.md",
        source_type="research_brief",
        weight=1.0,
        metadata={"content": "Bridgewater launch source text."},
        created_at=NOW,
    )


def _presenter_sets(
    series_profile_id: uuid.UUID,
) -> tuple[tuple[ReferenceDocument, ReferenceDocumentRevision, ReferenceBinding], ...]:
    """Return host and guest profiles bound to the series."""
    sets = []
    for offset, kind, name, summary in (
        (1, ReferenceDocumentKind.HOST_PROFILE, "Host One", "Host profile."),
        (2, ReferenceDocumentKind.GUEST_PROFILE, "Guest One", "Guest profile."),
    ):
        document = ReferenceDocument(
            id=uuid.UUID(f"00000000-0000-0000-0000-{600 + offset:012d}"),
            owner_series_profile_id=series_profile_id,
            kind=kind,
            lifecycle_state=ReferenceDocumentLifecycleState.ACTIVE,
            metadata={"name": name},
            created_at=NOW,
            updated_at=NOW,
        )
        revision = ReferenceDocumentRevision(
            id=uuid.UUID(f"00000000-0000-0000-0000-{700 + offset:012d}"),
            reference_document_id=document.id,
            content={"summary": summary},
            content_hash=f"presenter-{offset}",
            author="editor@example.test",
            change_note="Create presenter profile.",
            created_at=NOW,
        )
        binding = ReferenceBinding(
            id=uuid.UUID(f"00000000-0000-0000-0000-{800 + offset:012d}"),
            reference_document_revision_id=revision.id,
            target_kind=ReferenceBindingTargetKind.SERIES_PROFILE,
            series_profile_id=series_profile_id,
            episode_template_id=None,
            ingestion_job_id=None,
            effective_from_episode_id=None,
            created_at=NOW,
        )
        sets.append((document, revision, binding))
    return tuple(sets)
