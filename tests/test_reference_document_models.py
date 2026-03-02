"""Unit tests for reusable reference-document domain models."""

from __future__ import annotations

import datetime as dt
import uuid

import pytest

from episodic.canonical.domain import (
    ReferenceBinding,
    ReferenceBindingTargetKind,
    ReferenceDocument,
    ReferenceDocumentKind,
    ReferenceDocumentLifecycleState,
    ReferenceDocumentRevision,
)


def _build_reference_binding(
    *,
    target_kind: ReferenceBindingTargetKind,
    **kwargs: uuid.UUID | None,
) -> ReferenceBinding:
    """Build a reference binding for tests.

    Args:
        target_kind: The kind of binding target.
        **kwargs: Optional target identifiers (series_profile_id,
            episode_template_id, ingestion_job_id, effective_from_episode_id).
    """
    now = dt.datetime.now(dt.UTC)
    return ReferenceBinding(
        id=uuid.uuid4(),
        reference_document_revision_id=uuid.uuid4(),
        target_kind=target_kind,
        series_profile_id=kwargs.get("series_profile_id"),
        episode_template_id=kwargs.get("episode_template_id"),
        ingestion_job_id=kwargs.get("ingestion_job_id"),
        effective_from_episode_id=kwargs.get("effective_from_episode_id"),
        created_at=now,
    )


def test_reference_document_kind_supports_host_and_guest_profiles() -> None:
    """Host and guest profile kinds should be part of the reusable model."""
    assert ReferenceDocumentKind.HOST_PROFILE.value == "host_profile"
    assert ReferenceDocumentKind.GUEST_PROFILE.value == "guest_profile"


def test_reference_document_revision_requires_non_empty_content_hash() -> None:
    """Revision content hash must be a non-empty string."""
    now = dt.datetime.now(dt.UTC)

    for invalid_hash in ("", "   "):
        with pytest.raises(ValueError, match="content_hash"):
            ReferenceDocumentRevision(
                id=uuid.uuid4(),
                reference_document_id=uuid.uuid4(),
                content={},
                content_hash=invalid_hash,
                author="author@example.com",
                change_note="Empty or whitespace-only hash should fail.",
                created_at=now,
            )


def test_reference_binding_rejects_missing_target_identifier() -> None:
    """A binding should require exactly one concrete target identifier."""
    with pytest.raises(ValueError, match="exactly one target identifier"):
        _build_reference_binding(
            target_kind=ReferenceBindingTargetKind.SERIES_PROFILE,
        )


def test_reference_binding_rejects_target_kind_mismatch() -> None:
    """Target kind must match the populated target identifier field."""
    with pytest.raises(ValueError, match="does not match populated target"):
        _build_reference_binding(
            target_kind=ReferenceBindingTargetKind.SERIES_PROFILE,
            episode_template_id=uuid.uuid4(),
        )


def test_reference_binding_rejects_effective_from_for_non_series_target() -> None:
    """effective_from_episode_id should be series-target specific."""
    with pytest.raises(ValueError, match="effective_from_episode_id"):
        _build_reference_binding(
            target_kind=ReferenceBindingTargetKind.EPISODE_TEMPLATE,
            episode_template_id=uuid.uuid4(),
            effective_from_episode_id=uuid.uuid4(),
        )


def test_reference_binding_accepts_series_target_with_effective_from_episode() -> None:
    """Series-target bindings may include effective_from_episode_id."""
    series_profile_id = uuid.uuid4()
    effective_from_episode_id = uuid.uuid4()
    binding = _build_reference_binding(
        target_kind=ReferenceBindingTargetKind.SERIES_PROFILE,
        series_profile_id=series_profile_id,
        effective_from_episode_id=effective_from_episode_id,
    )

    assert binding.series_profile_id == series_profile_id
    assert binding.effective_from_episode_id == effective_from_episode_id


def test_reference_binding_accepts_ingestion_job_target() -> None:
    """Non-series bindings are accepted without effective_from_episode_id."""
    ingestion_job_id = uuid.uuid4()

    binding = _build_reference_binding(
        target_kind=ReferenceBindingTargetKind.INGESTION_JOB,
        ingestion_job_id=ingestion_job_id,
        effective_from_episode_id=None,
    )

    assert binding.target_kind is ReferenceBindingTargetKind.INGESTION_JOB
    assert binding.ingestion_job_id == ingestion_job_id
    assert binding.effective_from_episode_id is None


def test_reference_document_accepts_series_aligned_host_profile() -> None:
    """Reference documents should represent series-aligned host profiles."""
    now = dt.datetime.now(dt.UTC)
    document = ReferenceDocument(
        id=uuid.uuid4(),
        owner_series_profile_id=uuid.uuid4(),
        kind=ReferenceDocumentKind.HOST_PROFILE,
        lifecycle_state=ReferenceDocumentLifecycleState.ACTIVE,
        metadata={"display_name": "Host A"},
        created_at=now,
        updated_at=now,
    )

    assert document.kind is ReferenceDocumentKind.HOST_PROFILE
    assert document.lifecycle_state is ReferenceDocumentLifecycleState.ACTIVE
