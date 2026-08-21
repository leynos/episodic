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
from tests.snapshot_redaction import redact_snapshot_uuids

if typ.TYPE_CHECKING:
    from syrupy.assertion import SnapshotAssertion


def _assert_serialized_fields(
    actual: dict[str, object],
    expected: dict[str, object],
    *,
    required_keys: tuple[str, ...] = (),
) -> None:
    """Assert expected serializer fields and required generated keys."""
    for field, expected_value in expected.items():
        assert actual[field] == expected_value, (
            f"Serialized field {field!r} must match its domain value."
        )
    for field in required_keys:
        assert field in actual, f"Serialized output must contain {field!r}."


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
    defaults.update(overrides)
    return ReferenceDocument(**defaults)


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
    defaults.update(overrides)
    return ReferenceDocumentRevision(**defaults)


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
    defaults.update(overrides)
    return ReferenceBinding(**defaults)


def test_serialize_resolved_binding_structure(snapshot: SnapshotAssertion) -> None:
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

    stable_result = redact_snapshot_uuids(result)
    assert stable_result == snapshot, "actual output must match snapshot"


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

    _assert_serialized_fields(
        binding_result,
        {
            "id": str(binding.id),
            "reference_document_revision_id": str(revision.id),
            "target_kind": "series_profile",
            "series_profile_id": str(binding.series_profile_id),
            "episode_template_id": None,
            "ingestion_job_id": None,
            "effective_from_episode_id": None,
        },
        required_keys=("created_at",),
    )


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

    _assert_serialized_fields(
        revision_result,
        {
            "id": str(revision.id),
            "reference_document_id": str(document.id),
            "content": {"summary": "Custom summary"},
            "content_hash": "customhash456",
            "author": "author@example.com",
            "change_note": "Important change",
        },
        required_keys=("created_at",),
    )


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

    _assert_serialized_fields(
        document_result,
        {
            "id": str(document.id),
            "owner_series_profile_id": str(document.owner_series_profile_id),
            "kind": "guest_profile",
            "lifecycle_state": "archived",
            "metadata": {"name": "Guest Document"},
            "lock_version": 3,
        },
        required_keys=("created_at", "updated_at"),
    )


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

    assert binding_result["target_kind"] == "episode_template", (
        "Expected values to match"
    )
    assert binding_result["series_profile_id"] is None, "Expected value to be absent"
    assert binding_result["episode_template_id"] == str(template_id), (
        "Expected values to match"
    )


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

    assert binding_result["effective_from_episode_id"] == str(episode_id), (
        "Expected values to match"
    )


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
    assert isinstance(result["binding"]["id"], str), (
        "Expected value to have the required type"
    )
    assert isinstance(result["binding"]["reference_document_revision_id"], str), (
        "Expected value to have the required type"
    )
    assert isinstance(result["revision"]["id"], str), (
        "Expected value to have the required type"
    )
    assert isinstance(result["revision"]["reference_document_id"], str), (
        "Expected value to have the required type"
    )
    assert isinstance(result["document"]["id"], str), (
        "Expected value to have the required type"
    )
    assert isinstance(result["document"]["owner_series_profile_id"], str), (
        "Expected value to have the required type"
    )
