"""Tests for brief loader helpers."""

import typing as typ
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
from episodic.canonical.profile_templates._brief_loaders import (
    _raise_if_missing_ids,
    _serialize_bindings_for_owner,
)


class TestRaiseIfMissingIds:
    """Tests for this group."""

    def test_it_does_not_raise_when_no_ids_missing(self) -> None:
        """Test case."""
        shared_id = uuid.uuid4()
        _raise_if_missing_ids(
            expected_ids={shared_id},
            found_ids={shared_id},
            label="test",
        )

    def test_it_raises_value_error_when_ids_missing(self) -> None:
        """Test case."""
        missing = uuid.uuid4()

        with pytest.raises(ValueError, match="test:"):
            _raise_if_missing_ids(
                expected_ids={missing},
                found_ids=set(),
                label="test",
            )


class TestSerializeBindingsForOwner:
    """Tests for this group."""

    def test_it_raises_value_error_when_document_belongs_to_wrong_owner(
        self,
    ) -> None:
        """Raise when a binding references a document from a different owner."""
        now = None
        # shadow 'now' below to keep type-checker happy for frozen dataclasses
        import datetime as dt

        now = dt.datetime.now(tz=dt.UTC)
        owner_id = uuid.uuid4()
        other_id = uuid.uuid4()
        rev_id = uuid.uuid4()

        document = ReferenceDocument(
            id=uuid.uuid4(),
            owner_series_profile_id=other_id,
            kind=ReferenceDocumentKind.STYLE_GUIDE,
            lifecycle_state=ReferenceDocumentLifecycleState.ACTIVE,
            metadata={},
            created_at=now,
            updated_at=now,
        )
        revision = ReferenceDocumentRevision(
            id=rev_id,
            reference_document_id=document.id,
            content={},
            content_hash="hash",
            author=None,
            change_note=None,
            created_at=now,
        )
        binding = ReferenceBinding(
            id=uuid.uuid4(),
            reference_document_revision_id=rev_id,
            target_kind=ReferenceBindingTargetKind.SERIES_PROFILE,
            series_profile_id=owner_id,
            episode_template_id=None,
            ingestion_job_id=None,
            effective_from_episode_id=None,
            created_at=now,
        )

        with pytest.raises(ValueError, match="does not belong"):
            _serialize_bindings_for_owner(
                bindings=[binding],
                revisions_by_id={rev_id: revision},
                documents_by_id={document.id: document},
                owner_series_profile_id=owner_id,
            )

    def test_it_serializes_valid_bindings(self) -> None:
        """Test case."""
        import datetime as dt

        now = dt.datetime.now(tz=dt.UTC)
        owner_id = uuid.uuid4()
        rev_id = uuid.uuid4()

        document = ReferenceDocument(
            id=uuid.uuid4(),
            owner_series_profile_id=owner_id,
            kind=ReferenceDocumentKind.HOST_PROFILE,
            lifecycle_state=ReferenceDocumentLifecycleState.ACTIVE,
            metadata={},
            created_at=now,
            updated_at=now,
        )
        revision = ReferenceDocumentRevision(
            id=rev_id,
            reference_document_id=document.id,
            content={"data": "test"},
            content_hash="hash123",
            author="author",
            change_note="note",
            created_at=now,
        )
        binding = ReferenceBinding(
            id=uuid.uuid4(),
            reference_document_revision_id=rev_id,
            target_kind=ReferenceBindingTargetKind.SERIES_PROFILE,
            series_profile_id=owner_id,
            episode_template_id=None,
            ingestion_job_id=None,
            effective_from_episode_id=None,
            created_at=now,
        )

        results = _serialize_bindings_for_owner(
            bindings=[binding],
            revisions_by_id={rev_id: revision},
            documents_by_id={document.id: document},
            owner_series_profile_id=owner_id,
        )

        assert len(results) == 1
        assert results[0]["binding_id"] == str(binding.id)
        assert results[0]["document_id"] == str(document.id)
        assert results[0]["revision_id"] == str(revision.id)
        content = typ.cast("dict[str, object]", results[0]["content"])
        assert content["data"] == "test"
