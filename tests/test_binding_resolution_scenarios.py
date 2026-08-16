"""Table-driven reference-binding precedence scenarios."""

import datetime as dt
import typing as typ
import uuid

import pytest

from episodic.canonical.domain import (
    ReferenceBinding,
    ReferenceBindingTargetKind,
)
from episodic.canonical.reference_documents.resolution import resolve_bindings

if typ.TYPE_CHECKING:
    from tests.fixtures.binding import BindingFixtures

pytestmark = [pytest.mark.asyncio]


class _ScenarioParams(typ.NamedTuple):
    episode_key: typ.Literal["episode_middle", "episode_late"]
    revision_key: typ.Literal["revision_v2", "revision_v3"]
    resolve_key: typ.Literal["episode_middle", "episode_early"]
    expect_default: bool


@pytest.mark.parametrize(
    "scenario",
    [
        _ScenarioParams("episode_middle", "revision_v2", "episode_middle", False),  # noqa: FBT003  # Named tuple fields document these compact table-driven scenario values.
        _ScenarioParams("episode_late", "revision_v3", "episode_early", True),  # noqa: FBT003  # Named tuple fields document these compact table-driven scenario values.
    ],
    ids=["episode_specific_over_default", "fallback_to_default"],
)
async def test_resolve_bindings_scenario(
    uow_with_fixtures: BindingFixtures,
    scenario: _ScenarioParams,
) -> None:
    """Test binding resolution scenarios with episode precedence logic."""
    fixtures = uow_with_fixtures
    uow = fixtures["uow"]
    series = fixtures["series"]
    now = fixtures["now"]
    revision = (
        fixtures["revision_v2"]
        if scenario.revision_key == "revision_v2"
        else fixtures["revision_v3"]
    )
    episode = (
        fixtures["episode_middle"]
        if scenario.episode_key == "episode_middle"
        else fixtures["episode_late"]
    )

    binding_default = ReferenceBinding(
        id=uuid.uuid4(),
        reference_document_revision_id=fixtures["revision_v1"].id,
        target_kind=ReferenceBindingTargetKind.SERIES_PROFILE,
        series_profile_id=series.id,
        episode_template_id=None,
        ingestion_job_id=None,
        effective_from_episode_id=None,
        created_at=now - dt.timedelta(days=12),
    )
    binding_episode = ReferenceBinding(
        id=uuid.uuid4(),
        reference_document_revision_id=revision.id,
        target_kind=ReferenceBindingTargetKind.SERIES_PROFILE,
        series_profile_id=series.id,
        episode_template_id=None,
        ingestion_job_id=None,
        effective_from_episode_id=episode.id,
        created_at=now - dt.timedelta(days=6),
    )
    await uow.reference_bindings.add(binding_default)
    await uow.reference_bindings.add(binding_episode)
    await uow.commit()

    resolved = await resolve_bindings(
        uow,
        series_profile_id=series.id,
        episode_id=(
            fixtures["episode_middle"].id
            if scenario.resolve_key == "episode_middle"
            else fixtures["episode_early"].id
        ),
    )

    expected = binding_default if scenario.expect_default else binding_episode
    assert len(resolved) == 1, "must match"
    assert resolved[0].binding.id == expected.id, "must match"
    assert resolved[0].revision.id == expected.reference_document_revision_id, (
        "must match"
    )
