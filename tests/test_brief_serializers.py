"""Unit tests for brief-payload serialisation helpers."""

import datetime as dt
import uuid

from episodic.canonical.domain import (
    EpisodeTemplate,
    ReferenceBinding,
    ReferenceBindingTargetKind,
    ReferenceDocument,
    ReferenceDocumentKind,
    ReferenceDocumentLifecycleState,
    ReferenceDocumentRevision,
    SeriesProfile,
)
from episodic.canonical.profile_templates._brief_serializers import (
    _serialize_profile_for_brief,
    _serialize_reference_document_for_brief,
    _serialize_template_for_brief,
)


class TestSerializeProfileForBrief:
    """Tests for this group."""

    def test_it_includes_all_expected_keys(self) -> None:
        """Test case."""
        now = dt.datetime.now(tz=dt.UTC)
        profile = SeriesProfile(
            id=uuid.uuid4(),
            slug="test-series",
            title="Test Series",
            description="A test series",
            configuration={"tone": "casual"},
            guardrails={"max_length": 100},
            created_at=now,
            updated_at=now,
        )

        result = _serialize_profile_for_brief(profile, 3)

        assert result["id"] == str(profile.id)
        assert result["slug"] == "test-series"
        assert result["title"] == "Test Series"
        assert result["description"] == "A test series"
        assert result["configuration"] == {"tone": "casual"}
        assert result["guardrails"] == {"max_length": 100}
        assert result["revision"] == 3
        assert result["updated_at"] == now.isoformat()


class TestSerializeTemplateForBrief:
    """Tests for this group."""

    def test_it_includes_all_expected_keys(self) -> None:
        """Test case."""
        now = dt.datetime.now(tz=dt.UTC)
        series_id = uuid.uuid4()
        template = EpisodeTemplate(
            id=uuid.uuid4(),
            series_profile_id=series_id,
            slug="test-template",
            title="Test Template",
            description="A test template",
            structure={"segments": ["intro", "body"]},
            guardrails={"style": "formal"},
            created_at=now,
            updated_at=now,
        )

        result = _serialize_template_for_brief(template, 1)

        assert result["id"] == str(template.id)
        assert result["series_profile_id"] == str(series_id)
        assert result["slug"] == "test-template"
        assert result["title"] == "Test Template"
        assert result["description"] == "A test template"
        assert result["structure"] == {"segments": ["intro", "body"]}
        assert result["guardrails"] == {"style": "formal"}
        assert result["revision"] == 1
        assert result["updated_at"] == now.isoformat()


class TestSerializeReferenceDocumentForBrief:
    """Tests for this group."""

    def test_it_includes_all_expected_keys_with_effective_from(self) -> None:
        """Test case."""
        now = dt.datetime.now(tz=dt.UTC)
        doc_id = uuid.uuid4()
        series_id = uuid.uuid4()
        revision_id = uuid.uuid4()
        binding_id = uuid.uuid4()
        episode_id = uuid.uuid4()

        document = ReferenceDocument(
            id=doc_id,
            owner_series_profile_id=series_id,
            kind=ReferenceDocumentKind.STYLE_GUIDE,
            lifecycle_state=ReferenceDocumentLifecycleState.ACTIVE,
            metadata={"version": "2.0"},
            created_at=now,
            updated_at=now,
        )
        revision = ReferenceDocumentRevision(
            id=revision_id,
            reference_document_id=doc_id,
            content={"rules": ["rule1"]},
            content_hash="abc123",
            author="editor",
            change_note="Initial",
            created_at=now,
        )
        binding = ReferenceBinding(
            id=binding_id,
            reference_document_revision_id=revision_id,
            target_kind=ReferenceBindingTargetKind.SERIES_PROFILE,
            series_profile_id=series_id,
            episode_template_id=None,
            ingestion_job_id=None,
            effective_from_episode_id=episode_id,
            created_at=now,
        )

        result = _serialize_reference_document_for_brief(
            binding=binding,
            document=document,
            revision=revision,
        )

        assert result["binding_id"] == str(binding_id)
        assert result["document_id"] == str(doc_id)
        assert result["revision_id"] == str(revision_id)
        assert result["kind"] == "style_guide"
        assert result["target_kind"] == "series_profile"
        assert result["effective_from_episode_id"] == str(episode_id)
        assert result["lifecycle_state"] == "active"
        assert result["metadata"] == {"version": "2.0"}
        assert result["content"] == {"rules": ["rule1"]}
        assert result["content_hash"] == "abc123"

    def test_it_handles_none_effective_from_episode(self) -> None:
        """Test case."""
        now = dt.datetime.now(tz=dt.UTC)
        doc_id = uuid.uuid4()
        series_id = uuid.uuid4()
        revision_id = uuid.uuid4()
        binding_id = uuid.uuid4()

        document = ReferenceDocument(
            id=doc_id,
            owner_series_profile_id=series_id,
            kind=ReferenceDocumentKind.HOST_PROFILE,
            lifecycle_state=ReferenceDocumentLifecycleState.DRAFT,
            metadata={},
            created_at=now,
            updated_at=now,
        )
        revision = ReferenceDocumentRevision(
            id=revision_id,
            reference_document_id=doc_id,
            content={"data": {}},
            content_hash="hash",
            author=None,
            change_note=None,
            created_at=now,
        )
        binding = ReferenceBinding(
            id=binding_id,
            reference_document_revision_id=revision_id,
            target_kind=ReferenceBindingTargetKind.SERIES_PROFILE,
            series_profile_id=series_id,
            episode_template_id=None,
            ingestion_job_id=None,
            effective_from_episode_id=None,
            created_at=now,
        )

        result = _serialize_reference_document_for_brief(
            binding=binding,
            document=document,
            revision=revision,
        )

        assert result["effective_from_episode_id"] is None
