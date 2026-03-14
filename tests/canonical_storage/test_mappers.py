"""Unit tests for canonical storage mapper copy boundaries."""

import datetime as dt
import typing as typ
import uuid

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


def test_series_profile_mappers_deep_copy_guardrails() -> None:
    """Series-profile guardrails must not be shared across the mapper seam."""
    now = dt.datetime.now(dt.UTC)
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

    profile = _series_profile_from_record(record)
    profile_guardrails = profile.guardrails
    banned_phrases = typ.cast("list[str]", profile_guardrails["banned_phrases"])
    banned_phrases.clear()
    banned_phrases.extend(["updated"])

    assert record.guardrails["banned_phrases"] == ["viral sensation"], (
        "Expected record-to-domain mapping to deep copy guardrails."
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

    mapped_record = _series_profile_to_record(domain)
    mapped_banned_phrases = typ.cast("list[str]", domain.guardrails["banned_phrases"])
    mapped_banned_phrases.clear()
    mapped_banned_phrases.extend(["mutated"])

    assert mapped_record.guardrails["banned_phrases"] == ["citation needed"], (
        "Expected domain-to-record mapping to deep copy guardrails."
    )


def test_episode_template_mappers_deep_copy_guardrails() -> None:
    """Episode-template guardrails must not be shared across the mapper seam."""
    now = dt.datetime.now(dt.UTC)
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

    template = _episode_template_from_record(record)
    template_guardrails = template.guardrails
    required_sections = typ.cast("list[str]", template_guardrails["required_sections"])
    required_sections.clear()
    required_sections.extend(["intro"])

    assert record.guardrails["required_sections"] == ["intro", "main", "outro"], (
        "Expected record-to-domain mapping to deep copy template guardrails."
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

    mapped_record = _episode_template_to_record(domain)
    mapped_required_sections = typ.cast(
        "list[str]", domain.guardrails["required_sections"]
    )
    mapped_required_sections.clear()
    mapped_required_sections.extend(["analysis"])

    assert mapped_record.guardrails["required_sections"] == [
        "intro",
        "analysis",
        "outro",
    ], "Expected domain-to-record mapping to deep copy template guardrails."
