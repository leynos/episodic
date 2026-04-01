"""Unit tests for API serializers."""

import datetime as dt
import typing as typ
import uuid

from episodic.api.serializers import serialize_resolved_binding
from episodic.canonical.domain import (
    ReferenceBinding,
    ReferenceBindingTargetKind,
    ReferenceDocument,
    ReferenceDocumentKind,
    ReferenceDocumentLifecycleState,
    ReferenceDocumentRevision,
)
from episodic.canonical.reference_documents import ResolvedBinding


def _make_reference_document(**overrides: object) -> ReferenceDocument:
    """Create a ReferenceDocument with default test values."""
    defaults: dict[str, typ.Any] = {
        "id": uuid.uuid4(),
        "owner_series_profile_id": uuid.uuid4(),
        "kind": ReferenceDocumentKind.STYLE_GUIDE,
        "lifecycle_state": ReferenceDocumentLifecycleState.ACTIVE,
        "metadata": {"name": "Test Document"},
        "lock_version": 1,
        "created_at": dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
        "updated_at": dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
    }
    defaults.update(overrides)  # type: ignore[arg-type]
    return typ.cast("ReferenceDocument", ReferenceDocument(**defaults))


def _make_reference_document_revision(
    **overrides: object,
) -> ReferenceDocumentRevision:
    """Create a ReferenceDocumentRevision with default test values."""
    defaults: dict[str, typ.Any] = {
        "id": uuid.uuid4(),
        "reference_document_id": uuid.uuid4(),
        "content": {"summary": "Test content"},
        "content_hash": "abc123hash",
        "author": "test@example.com",
        "change_note": "Test change",
        "created_at": dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
    }
    defaults.update(overrides)  # type: ignore[arg-type]
    return typ.cast("ReferenceDocumentRevision", ReferenceDocumentRevision(**defaults))


def _make_reference_binding(**overrides: object) -> ReferenceBinding:
    """Create a ReferenceBinding with default test values."""
    defaults: dict[str, typ.Any] = {
        "id": uuid.uuid4(),
        "reference_document_revision_id": uuid.uuid4(),
        "target_kind": ReferenceBindingTargetKind.SERIES_PROFILE,
        "series_profile_id": uuid.uuid4(),
        "episode_template_id": None,
        "ingestion_job_id": None,
        "effective_from_episode_id": None,
        "created_at": dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
    }
    defaults.update(overrides)  # type: ignore[arg-type]
    return typ.cast("ReferenceBinding", ReferenceBinding(**defaults))


def test_serialize_resolved_binding_structure() -> None:
    """serialize_resolved_binding should return binding, revision, and document keys."""
    document = _make_reference_document()
    revision = _make_reference_document_revision(
        reference_document_id=document.id,
    )
    binding = _make_reference_binding(
        reference_document_revision_id=revision.id,
    )
    resolved = ResolvedBinding(
        binding=binding,
        revision=revision,
        document=document,
    )

    result = serialize_resolved_binding(resolved)

    assert "binding" in result
    assert "revision" in result
    assert "document" in result


def test_serialize_resolved_binding_binding_content() -> None:
    """serialize_resolved_binding should include correct binding fields."""
    document = _make_reference_document()
    revision = _make_reference_document_revision(
        reference_document_id=document.id,
    )
    binding = _make_reference_binding(
        reference_document_revision_id=revision.id,
        target_kind=ReferenceBindingTargetKind.SERIES_PROFILE,
    )
    resolved = ResolvedBinding(
        binding=binding,
        revision=revision,
        document=document,
    )

    result = serialize_resolved_binding(resolved)
    binding_result = typ.cast("dict[str, typ.Any]", result["binding"])

    assert binding_result["id"] == str(binding.id)
    assert binding_result["reference_document_revision_id"] == str(revision.id)
    assert binding_result["target_kind"] == "series_profile"
    assert binding_result["series_profile_id"] == str(binding.series_profile_id)
    assert binding_result["episode_template_id"] is None
    assert binding_result["ingestion_job_id"] is None
    assert binding_result["effective_from_episode_id"] is None
    assert "created_at" in binding_result


def test_serialize_resolved_binding_revision_content() -> None:
    """serialize_resolved_binding should include correct revision fields."""
    document = _make_reference_document()
    revision = _make_reference_document_revision(
        reference_document_id=document.id,
        content={"summary": "Custom summary"},
        content_hash="customhash456",
        author="author@example.com",
        change_note="Important change",
    )
    binding = _make_reference_binding(
        reference_document_revision_id=revision.id,
    )
    resolved = ResolvedBinding(
        binding=binding,
        revision=revision,
        document=document,
    )

    result = serialize_resolved_binding(resolved)
    revision_result = typ.cast("dict[str, typ.Any]", result["revision"])

    assert revision_result["id"] == str(revision.id)
    assert revision_result["reference_document_id"] == str(document.id)
    assert revision_result["content"] == {"summary": "Custom summary"}
    assert revision_result["content_hash"] == "customhash456"
    assert revision_result["author"] == "author@example.com"
    assert revision_result["change_note"] == "Important change"
    assert "created_at" in revision_result


def test_serialize_resolved_binding_document_content() -> None:
    """serialize_resolved_binding should include correct document fields."""
    document = _make_reference_document(
        kind=ReferenceDocumentKind.GUEST_PROFILE,
        lifecycle_state=ReferenceDocumentLifecycleState.ARCHIVED,
        metadata={"name": "Guest Document"},
        lock_version=3,
    )
    revision = _make_reference_document_revision(
        reference_document_id=document.id,
    )
    binding = _make_reference_binding(
        reference_document_revision_id=revision.id,
    )
    resolved = ResolvedBinding(
        binding=binding,
        revision=revision,
        document=document,
    )

    result = serialize_resolved_binding(resolved)
    document_result = typ.cast("dict[str, typ.Any]", result["document"])

    assert document_result["id"] == str(document.id)
    assert document_result["owner_series_profile_id"] == str(
        document.owner_series_profile_id
    )
    assert document_result["kind"] == "guest_profile"
    assert document_result["lifecycle_state"] == "archived"
    assert document_result["metadata"] == {"name": "Guest Document"}
    assert document_result["lock_version"] == 3
    assert "created_at" in document_result
    assert "updated_at" in document_result


def test_serialize_resolved_binding_with_template_target() -> None:
    """serialize_resolved_binding should handle template bindings correctly."""
    document = _make_reference_document()
    revision = _make_reference_document_revision(
        reference_document_id=document.id,
    )
    template_id = uuid.uuid4()
    binding = _make_reference_binding(
        reference_document_revision_id=revision.id,
        target_kind=ReferenceBindingTargetKind.EPISODE_TEMPLATE,
        series_profile_id=None,
        episode_template_id=template_id,
    )
    resolved = ResolvedBinding(
        binding=binding,
        revision=revision,
        document=document,
    )

    result = serialize_resolved_binding(resolved)
    binding_result = typ.cast("dict[str, typ.Any]", result["binding"])

    assert binding_result["target_kind"] == "episode_template"
    assert binding_result["series_profile_id"] is None
    assert binding_result["episode_template_id"] == str(template_id)


def test_serialize_resolved_binding_with_effective_from_episode() -> None:
    """serialize_resolved_binding should include effective_from_episode_id when set."""
    document = _make_reference_document()
    revision = _make_reference_document_revision(
        reference_document_id=document.id,
    )
    episode_id = uuid.uuid4()
    binding = _make_reference_binding(
        reference_document_revision_id=revision.id,
        effective_from_episode_id=episode_id,
    )
    resolved = ResolvedBinding(
        binding=binding,
        revision=revision,
        document=document,
    )

    result = serialize_resolved_binding(resolved)
    binding_result = typ.cast("dict[str, typ.Any]", result["binding"])

    assert binding_result["effective_from_episode_id"] == str(episode_id)


def test_serialize_resolved_binding_uuid_string_conversion() -> None:
    """serialize_resolved_binding should convert all UUIDs to strings."""
    document = _make_reference_document()
    revision = _make_reference_document_revision(
        reference_document_id=document.id,
    )
    binding = _make_reference_binding(
        reference_document_revision_id=revision.id,
    )
    resolved = ResolvedBinding(
        binding=binding,
        revision=revision,
        document=document,
    )

    result = serialize_resolved_binding(resolved)

    # All ID fields should be strings, not UUID objects
    assert isinstance(result["binding"]["id"], str)
    assert isinstance(result["binding"]["reference_document_revision_id"], str)
    assert isinstance(result["revision"]["id"], str)
    assert isinstance(result["revision"]["reference_document_id"], str)
    assert isinstance(result["document"]["id"], str)
    assert isinstance(result["document"]["owner_series_profile_id"], str)
