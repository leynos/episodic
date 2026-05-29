"""Unit tests for binding-target validation helpers."""

import uuid

import pytest

from episodic.canonical.domain import ReferenceBindingTargetKind
from episodic.canonical.reference_documents._binding_validation import (
    _assert_binding_target_shape,
    _assert_effective_from_series_profile_only,
    _parse_binding_ids,
)
from episodic.canonical.reference_documents.types import (
    ReferenceBindingData,
    ReferenceValidationError,
)


class TestParseBindingIds:
    """Tests for _parse_binding_ids."""

    def test_it_parses_all_uuid_fields_with_valid_input(self) -> None:
        """Parse all UUID fields correctly from a valid payload."""
        revision_id = uuid.uuid4()
        series_id = uuid.uuid4()
        template_id = uuid.uuid4()
        job_id = uuid.uuid4()
        episode_id = uuid.uuid4()

        data = ReferenceBindingData(
            reference_document_revision_id=str(revision_id),
            target_kind="series_profile",
            series_profile_id=str(series_id),
            episode_template_id=str(template_id),
            ingestion_job_id=str(job_id),
            effective_from_episode_id=str(episode_id),
        )

        result = _parse_binding_ids(data)

        assert result.revision_id == revision_id
        assert result.target_kind == ReferenceBindingTargetKind.SERIES_PROFILE
        assert result.series_profile_id == series_id
        assert result.episode_template_id == template_id
        assert result.ingestion_job_id == job_id
        assert result.effective_from_episode_id == episode_id

    def test_it_handles_none_fields(self) -> None:
        """Return None for optional target and effective-from fields."""
        revision_id = uuid.uuid4()

        data = ReferenceBindingData(
            reference_document_revision_id=str(revision_id),
            target_kind="series_profile",
            series_profile_id=None,
            episode_template_id=None,
            ingestion_job_id=None,
            effective_from_episode_id=None,
        )

        result = _parse_binding_ids(data)

        assert result.revision_id == revision_id
        assert result.series_profile_id is None
        assert result.episode_template_id is None
        assert result.ingestion_job_id is None
        assert result.effective_from_episode_id is None

    @pytest.mark.parametrize(
        ("revision_id", "target_kind_str", "expected_match"),
        [
            ("not-a-uuid", "series_profile", "Invalid UUID"),
            (str(uuid.uuid4()), "not-a-kind", "Unsupported"),
        ],
    )
    def test_it_rejects_invalid_input(
        self,
        revision_id: str,
        target_kind_str: str,
        expected_match: str,
    ) -> None:
        """Raise ReferenceValidationError for malformed UUID or unknown target kind."""
        data = ReferenceBindingData(
            reference_document_revision_id=revision_id,
            target_kind=target_kind_str,
            series_profile_id=None,
            episode_template_id=None,
            ingestion_job_id=None,
            effective_from_episode_id=None,
        )
        with pytest.raises(ReferenceValidationError, match=expected_match):
            _parse_binding_ids(data)


class TestAssertBindingTargetShape:
    """Tests for _assert_binding_target_shape."""

    def test_it_accepts_exactly_one_populated_target(self) -> None:
        """Accept a single populated target identifier matching target_kind."""
        _assert_binding_target_shape(
            ReferenceBindingTargetKind.SERIES_PROFILE,
            {
                ReferenceBindingTargetKind.SERIES_PROFILE: uuid.uuid4(),
                ReferenceBindingTargetKind.EPISODE_TEMPLATE: None,
                ReferenceBindingTargetKind.INGESTION_JOB: None,
            },
        )

    @pytest.mark.parametrize(
        ("target_map", "expected_match"),
        [
            (
                {
                    ReferenceBindingTargetKind.SERIES_PROFILE: None,
                    ReferenceBindingTargetKind.EPISODE_TEMPLATE: None,
                    ReferenceBindingTargetKind.INGESTION_JOB: None,
                },
                "must set exactly one target identifier",
            ),
            (
                {
                    ReferenceBindingTargetKind.SERIES_PROFILE: None,
                    ReferenceBindingTargetKind.EPISODE_TEMPLATE: uuid.uuid4(),
                    ReferenceBindingTargetKind.INGESTION_JOB: None,
                },
                "target_kind does not match populated target",
            ),
        ],
    )
    def test_it_rejects_invalid_shape(
        self,
        target_map: dict[ReferenceBindingTargetKind, uuid.UUID | None],
        expected_match: str,
    ) -> None:
        """Raise ReferenceValidationError for zero or mismatched populated targets."""
        with pytest.raises(ReferenceValidationError, match=expected_match):
            _assert_binding_target_shape(
                ReferenceBindingTargetKind.SERIES_PROFILE,
                target_map,
            )


class TestAssertEffectiveFromSeriesProfileOnly:
    """Tests for _assert_effective_from_series_profile_only."""

    def test_it_accepts_effective_from_for_series_profile_target(
        self,
    ) -> None:
        """Allow effective_from for SERIES_PROFILE targets."""
        _assert_effective_from_series_profile_only(
            ReferenceBindingTargetKind.SERIES_PROFILE,
            uuid.uuid4(),
        )

    def test_it_accepts_none_effective_from_for_any_target(self) -> None:
        """Allow None effective_from for any target kind."""
        _assert_effective_from_series_profile_only(
            ReferenceBindingTargetKind.EPISODE_TEMPLATE, None
        )

    def test_it_rejects_effective_from_for_non_series_target(self) -> None:
        """Raise when effective_from is set on a non-SERIES_PROFILE target."""
        with pytest.raises(
            ReferenceValidationError,
            match="effective_from_episode_id is only valid",
        ):
            _assert_effective_from_series_profile_only(
                ReferenceBindingTargetKind.EPISODE_TEMPLATE,
                uuid.uuid4(),
            )
