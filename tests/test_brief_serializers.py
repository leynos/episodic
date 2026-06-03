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

        assert result["id"] == str(profile.id), "expected id to match profile.id"
        assert result["slug"] == "test-series", "expected slug to match profile.slug"
        assert result["title"] == "Test Series", "expected title to match profile.title"
        assert result["description"] == "A test series", (
            "expected description to match profile.description"
        )
        assert result["configuration"] == {"tone": "casual"}, (
            "expected configuration to match profile.configuration"
        )
        assert result["guardrails"] == {"max_length": 100}, (
            "expected guardrails to match profile.guardrails"
        )
        assert result["revision"] == 3, "expected revision to match input revision"
        assert result["updated_at"] == now.isoformat(), (
            "expected updated_at to match now.isoformat()"
        )


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

        assert result["id"] == str(template.id), "expected id to match template.id"
        assert result["series_profile_id"] == str(series_id), (
            "expected series_profile_id to match series_id"
        )
        assert result["slug"] == "test-template", "expected slug to match template.slug"
        assert result["title"] == "Test Template", (
            "expected title to match template.title"
        )
        assert result["description"] == "A test template", (
            "expected description to match template.description"
        )
        assert result["structure"] == {"segments": ["intro", "body"]}, (
            "expected structure to match template.structure"
        )
        assert result["guardrails"] == {"style": "formal"}, (
            "expected guardrails to match template.guardrails"
        )
        assert result["revision"] == 1, "expected revision to match input revision"
        assert result["updated_at"] == now.isoformat(), (
            "expected updated_at to match now.isoformat()"
        )


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

        assert result["binding_id"] == str(binding_id), (
            f"expected result binding_id to match binding_id {binding_id}"
        )
        assert result["document_id"] == str(doc_id), (
            f"expected result document_id to match doc_id {doc_id}"
        )
        assert result["revision_id"] == str(revision_id), (
            f"expected result revision_id to match revision_id {revision_id}"
        )
        assert result["kind"] == "style_guide", (
            f"expected result kind style_guide, got {result['kind']}"
        )
        assert result["target_kind"] == "series_profile", (
            f"expected result target_kind series_profile, got {result['target_kind']}"
        )
        assert result["effective_from_episode_id"] == str(episode_id), (
            "expected result effective_from_episode_id to match "
            f"episode_id {episode_id}"
        )
        assert result["lifecycle_state"] == "active", (
            f"expected result lifecycle_state active, got {result['lifecycle_state']}"
        )
        assert result["metadata"] == {"version": "2.0"}, (
            f"expected metadata to match document metadata, got {result['metadata']}"
        )
        assert result["content"] == {"rules": ["rule1"]}, (
            f"expected content to match revision content, got {result['content']}"
        )
        assert result["content_hash"] == "abc123", (
            f"expected result content_hash abc123, got {result['content_hash']}"
        )

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

        assert result["effective_from_episode_id"] is None, (
            "expected effective_from_episode_id to be None, got "
            f"{result['effective_from_episode_id']}"
        )
