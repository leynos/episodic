"""Unit tests for canonical storage mapper copy boundaries."""

import dataclasses as dc
import datetime as dt
import typing as typ
import uuid

import pytest

from episodic.canonical.domain import EpisodeTemplate, SeriesProfile
from episodic.canonical.storage.mappers import (
    _episode_template_from_record,
    _episode_template_to_record,
    _series_profile_from_record,
    _series_profile_to_record,
)
from episodic.canonical.storage.models import (
    EpisodeTemplateRecord,
    SeriesProfileRecord,
)

if typ.TYPE_CHECKING:
    from episodic.canonical.domain import JsonMapping


def _build_series_profile_copy_boundary(
    now: dt.datetime,
) -> _MapperCopyBoundaryFixture:
    """Build the series-profile mapper copy-boundary scenario."""
    record_guardrails = {
        "instruction": "Stay factual.",
        "banned_phrases": ["viral sensation"],
    }
    record = SeriesProfileRecord(
        id=uuid.uuid4(),
        slug="science-hour",
        title="Science Hour",
        description=None,
        configuration={"tone": "measured"},
        guardrails=record_guardrails,
        created_at=now,
        updated_at=now,
    )
    domain_guardrails: JsonMapping = {
        "instruction": "Stay factual.",
        "banned_phrases": ["citation needed"],
    }
    domain = SeriesProfile(
        id=uuid.uuid4(),
        slug="history-hour",
        title="History Hour",
        description=None,
        configuration={"tone": "careful"},
        guardrails=domain_guardrails,
        created_at=now,
        updated_at=now,
    )
    return _MapperCopyBoundaryFixture(
        mapped_domain=_series_profile_from_record(record),
        domain=domain,
        original_record_guardrails=record.guardrails,
        mapped_record_guardrails=_series_profile_to_record(domain).guardrails,
        guardrail_key="banned_phrases",
        record_mutation=["updated"],
        domain_mutation=["mutated"],
        record_expected=["viral sensation"],
        domain_expected=["citation needed"],
    )


def _build_episode_template_copy_boundary(
    now: dt.datetime,
) -> _MapperCopyBoundaryFixture:
    """Build the episode-template mapper copy-boundary scenario."""
    record_guardrails = {
        "instruction": "Open with a headline.",
        "required_sections": ["intro", "main", "outro"],
    }
    record = EpisodeTemplateRecord(
        id=uuid.uuid4(),
        series_profile_id=uuid.uuid4(),
        slug="weekly-template",
        title="Weekly Template",
        description=None,
        structure={"segments": ["intro", "main", "outro"]},
        guardrails=record_guardrails,
        created_at=now,
        updated_at=now,
    )
    domain_guardrails: JsonMapping = {
        "instruction": "Close with a recap.",
        "required_sections": ["intro", "analysis", "outro"],
    }
    domain = EpisodeTemplate(
        id=uuid.uuid4(),
        series_profile_id=uuid.uuid4(),
        slug="analysis-template",
        title="Analysis Template",
        description=None,
        structure={"segments": ["intro", "analysis", "outro"]},
        guardrails=domain_guardrails,
        created_at=now,
        updated_at=now,
    )
    return _MapperCopyBoundaryFixture(
        mapped_domain=_episode_template_from_record(record),
        domain=domain,
        original_record_guardrails=record.guardrails,
        mapped_record_guardrails=_episode_template_to_record(domain).guardrails,
        guardrail_key="required_sections",
        record_mutation=["intro"],
        domain_mutation=["analysis"],
        record_expected=["intro", "main", "outro"],
        domain_expected=["intro", "analysis", "outro"],
    )


@dc.dataclass(frozen=True, slots=True)
class _MapperCopyBoundaryFixture:
    """Bundle one mapper copy-boundary scenario."""

    mapped_domain: SeriesProfile | EpisodeTemplate
    domain: SeriesProfile | EpisodeTemplate
    original_record_guardrails: dict[str, object]
    mapped_record_guardrails: dict[str, object]
    guardrail_key: str
    record_mutation: list[str]
    domain_mutation: list[str]
    record_expected: list[str]
    domain_expected: list[str]


@pytest.fixture
def mapper_copy_boundary(
    request: pytest.FixtureRequest,
) -> _MapperCopyBoundaryFixture:
    """Build one mapper copy-boundary scenario for parametrized testing."""
    now = dt.datetime.now(dt.UTC)
    case_name = typ.cast("str", request.param)
    if case_name == "series_profile":
        return _build_series_profile_copy_boundary(now)
    return _build_episode_template_copy_boundary(now)


@pytest.mark.parametrize(
    "mapper_copy_boundary",
    ["series_profile", "episode_template"],
    indirect=True,
)
def test_mapper_guardrails_deep_copy(
    mapper_copy_boundary: _MapperCopyBoundaryFixture,
) -> None:
    """Mapper guardrails must not be shared across the domain/record seam."""
    mapped_domain_guardrails = mapper_copy_boundary.mapped_domain.guardrails
    mapped_domain_values = typ.cast(
        "list[str]", mapped_domain_guardrails[mapper_copy_boundary.guardrail_key]
    )
    mapped_domain_values.clear()
    mapped_domain_values.extend(mapper_copy_boundary.record_mutation)

    domain_values = typ.cast(
        "list[str]",
        mapper_copy_boundary.domain.guardrails[mapper_copy_boundary.guardrail_key],
    )
    domain_values.clear()
    domain_values.extend(mapper_copy_boundary.domain_mutation)

    assert (
        mapper_copy_boundary.original_record_guardrails[
            mapper_copy_boundary.guardrail_key
        ]
        == mapper_copy_boundary.record_expected
    ), "Expected record-to-domain mapping to deep copy guardrails."
    assert (
        mapper_copy_boundary.mapped_record_guardrails[
            mapper_copy_boundary.guardrail_key
        ]
        == mapper_copy_boundary.domain_expected
    ), "Expected domain-to-record mapping to deep copy guardrails."
