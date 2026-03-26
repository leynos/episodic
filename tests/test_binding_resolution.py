"""Unit tests for reference binding resolution algorithm."""

import datetime as dt
import typing as typ
import uuid

import pytest
import pytest_asyncio

from episodic.canonical.domain import (
    ReferenceBinding,
    ReferenceBindingTargetKind,
)
from episodic.canonical.reference_documents.resolution import (
    ResolvedBinding,
    resolve_bindings,
)

if typ.TYPE_CHECKING:
    from episodic.canonical.ports import CanonicalUnitOfWork

from tests.conftest import create_episode_template_for_binding_tests

pytestmark = pytest.mark.asyncio


# Alias fixture for backward compatibility
@pytest_asyncio.fixture
def uow_with_fixtures(uow_with_binding_fixtures):  # noqa: ANN001, ANN201
    """Alias for uow_with_binding_fixtures from conftest."""
    yield uow_with_binding_fixtures


async def test_resolve_bindings_returns_empty_when_no_bindings_exist(
    uow_with_fixtures,  # noqa: ANN001
) -> None:
    """Resolution returns empty list when no bindings exist for series profile."""
    fixtures = uow_with_fixtures
    uow: CanonicalUnitOfWork = fixtures["uow"]
    series = fixtures["series"]

    resolved = await resolve_bindings(uow, series_profile_id=series.id)

    assert resolved == []


async def test_resolve_bindings_returns_empty_for_nonexistent_episode_id(
    uow_with_fixtures,  # noqa: ANN001
) -> None:
    """Resolution returns empty list when episode_id does not exist in the DB."""
    fixtures = uow_with_fixtures
    uow: CanonicalUnitOfWork = fixtures["uow"]
    series = fixtures["series"]
    revision_v1 = fixtures["revision_v1"]
    now = fixtures["now"]

    binding = ReferenceBinding(
        id=uuid.uuid4(),
        reference_document_revision_id=revision_v1.id,
        target_kind=ReferenceBindingTargetKind.SERIES_PROFILE,
        series_profile_id=series.id,
        episode_template_id=None,
        ingestion_job_id=None,
        effective_from_episode_id=None,
        created_at=now,
    )
    await uow.reference_bindings.add(binding)
    await uow.commit()

    nonexistent_episode_id = uuid.uuid4()

    resolved = await resolve_bindings(
        uow,
        series_profile_id=series.id,
        episode_id=nonexistent_episode_id,
    )

    assert resolved == []


async def test_resolve_bindings_returns_default_binding_when_no_episode_context(
    uow_with_fixtures,  # noqa: ANN001
) -> None:
    """When no episode_id is provided, resolution includes default binding."""
    fixtures = uow_with_fixtures
    uow: CanonicalUnitOfWork = fixtures["uow"]
    series = fixtures["series"]
    revision_v1 = fixtures["revision_v1"]

    binding = ReferenceBinding(
        id=uuid.uuid4(),
        reference_document_revision_id=revision_v1.id,
        target_kind=ReferenceBindingTargetKind.SERIES_PROFILE,
        series_profile_id=series.id,
        episode_template_id=None,
        ingestion_job_id=None,
        effective_from_episode_id=None,
        created_at=fixtures["now"],
    )
    await uow.reference_bindings.add(binding)
    await uow.commit()

    resolved = await resolve_bindings(uow, series_profile_id=series.id)

    assert len(resolved) == 1
    assert isinstance(resolved[0], ResolvedBinding)
    assert resolved[0].binding.id == binding.id
    assert resolved[0].revision.id == revision_v1.id


class _ScenarioParams(typ.NamedTuple):
    episode_key: str
    revision_key: str
    resolve_key: str
    expect_default: bool


@pytest.mark.parametrize(
    "scenario",
    [
        _ScenarioParams("episode_middle", "revision_v2", "episode_middle", False),  # noqa: FBT003
        _ScenarioParams("episode_late", "revision_v3", "episode_early", True),  # noqa: FBT003
    ],
    ids=["episode_specific_over_default", "fallback_to_default"],
)
async def test_resolve_bindings_scenario(
    uow_with_fixtures,  # noqa: ANN001
    scenario: _ScenarioParams,
) -> None:
    """Test binding resolution scenarios with episode precedence logic."""
    fixtures = uow_with_fixtures
    uow = fixtures["uow"]
    series = fixtures["series"]
    now = fixtures["now"]

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
        reference_document_revision_id=fixtures[scenario.revision_key].id,
        target_kind=ReferenceBindingTargetKind.SERIES_PROFILE,
        series_profile_id=series.id,
        episode_template_id=None,
        ingestion_job_id=None,
        effective_from_episode_id=fixtures[scenario.episode_key].id,
        created_at=now - dt.timedelta(days=6),
    )
    await uow.reference_bindings.add(binding_default)
    await uow.reference_bindings.add(binding_episode)
    await uow.commit()

    resolved = await resolve_bindings(
        uow,
        series_profile_id=series.id,
        episode_id=fixtures[scenario.resolve_key].id,
    )

    expected = binding_default if scenario.expect_default else binding_episode
    assert len(resolved) == 1
    assert resolved[0].binding.id == expected.id
    assert resolved[0].revision.id == expected.reference_document_revision_id


async def test_resolve_bindings_selects_latest_applicable_episode_binding(  # noqa: PLR0914
    uow_with_fixtures,  # noqa: ANN001
) -> None:
    """Resolution selects the binding with the latest effective_from_episode_id."""
    fixtures = uow_with_fixtures
    uow: CanonicalUnitOfWork = fixtures["uow"]
    series = fixtures["series"]
    episode_early = fixtures["episode_early"]
    episode_middle = fixtures["episode_middle"]
    episode_late = fixtures["episode_late"]
    revision_v1 = fixtures["revision_v1"]
    revision_v2 = fixtures["revision_v2"]
    revision_v3 = fixtures["revision_v3"]

    binding_early = ReferenceBinding(
        id=uuid.uuid4(),
        reference_document_revision_id=revision_v1.id,
        target_kind=ReferenceBindingTargetKind.SERIES_PROFILE,
        series_profile_id=series.id,
        episode_template_id=None,
        ingestion_job_id=None,
        effective_from_episode_id=episode_early.id,
        created_at=fixtures["now"] - dt.timedelta(days=11),
    )
    binding_middle = ReferenceBinding(
        id=uuid.uuid4(),
        reference_document_revision_id=revision_v2.id,
        target_kind=ReferenceBindingTargetKind.SERIES_PROFILE,
        series_profile_id=series.id,
        episode_template_id=None,
        ingestion_job_id=None,
        effective_from_episode_id=episode_middle.id,
        created_at=fixtures["now"] - dt.timedelta(days=6),
    )
    binding_late = ReferenceBinding(
        id=uuid.uuid4(),
        reference_document_revision_id=revision_v3.id,
        target_kind=ReferenceBindingTargetKind.SERIES_PROFILE,
        series_profile_id=series.id,
        episode_template_id=None,
        ingestion_job_id=None,
        effective_from_episode_id=episode_late.id,
        created_at=fixtures["now"] - dt.timedelta(days=1),
    )

    for b in [binding_early, binding_middle, binding_late]:
        await uow.reference_bindings.add(b)
    await uow.commit()

    resolved_early = await resolve_bindings(
        uow, series_profile_id=series.id, episode_id=episode_early.id
    )
    assert len(resolved_early) == 1
    assert resolved_early[0].binding.id == binding_early.id
    assert resolved_early[0].revision.id == revision_v1.id

    resolved_middle = await resolve_bindings(
        uow, series_profile_id=series.id, episode_id=episode_middle.id
    )
    assert len(resolved_middle) == 1
    assert resolved_middle[0].binding.id == binding_middle.id
    assert resolved_middle[0].revision.id == revision_v2.id

    resolved_late = await resolve_bindings(
        uow, series_profile_id=series.id, episode_id=episode_late.id
    )
    assert len(resolved_late) == 1
    assert resolved_late[0].binding.id == binding_late.id
    assert resolved_late[0].revision.id == revision_v3.id


async def test_resolve_bindings_excludes_future_episode_bindings(
    uow_with_fixtures,  # noqa: ANN001
) -> None:
    """Bindings with effective_from_episode_id after target episode are excluded."""
    fixtures = uow_with_fixtures
    uow: CanonicalUnitOfWork = fixtures["uow"]
    series = fixtures["series"]
    episode_early = fixtures["episode_early"]
    episode_late = fixtures["episode_late"]
    revision_v3 = fixtures["revision_v3"]

    binding_late = ReferenceBinding(
        id=uuid.uuid4(),
        reference_document_revision_id=revision_v3.id,
        target_kind=ReferenceBindingTargetKind.SERIES_PROFILE,
        series_profile_id=series.id,
        episode_template_id=None,
        ingestion_job_id=None,
        effective_from_episode_id=episode_late.id,
        created_at=fixtures["now"] - dt.timedelta(days=1),
    )
    await uow.reference_bindings.add(binding_late)
    await uow.commit()

    resolved = await resolve_bindings(
        uow, series_profile_id=series.id, episode_id=episode_early.id
    )

    assert resolved == []


async def test_resolve_bindings_includes_template_bindings(
    uow_with_fixtures,  # noqa: ANN001
) -> None:
    """Template bindings are included when template_id is provided."""
    uow = uow_with_fixtures["uow"]
    series = uow_with_fixtures["series"]
    now = uow_with_fixtures["now"]

    template = await create_episode_template_for_binding_tests(uow, series.id, now)

    for rev_key, kind, tmpl_id in [
        ("revision_v1", ReferenceBindingTargetKind.SERIES_PROFILE, None),
        ("revision_v2", ReferenceBindingTargetKind.EPISODE_TEMPLATE, template.id),
    ]:
        await uow.reference_bindings.add(
            ReferenceBinding(
                id=uuid.uuid4(),
                reference_document_revision_id=uow_with_fixtures[rev_key].id,
                target_kind=kind,
                series_profile_id=(
                    series.id
                    if kind == ReferenceBindingTargetKind.SERIES_PROFILE
                    else None
                ),
                episode_template_id=tmpl_id,
                ingestion_job_id=None,
                effective_from_episode_id=None,
                created_at=now,
            )
        )
    await uow.commit()

    resolved = await resolve_bindings(
        uow, series_profile_id=series.id, template_id=template.id
    )

    assert len(resolved) == 2
    resolved_revision_ids = {r.revision.id for r in resolved}
    assert resolved_revision_ids == {
        uow_with_fixtures["revision_v1"].id,
        uow_with_fixtures["revision_v2"].id,
    }


async def test_resolve_bindings_merges_template_with_episode(
    uow_with_fixtures,  # noqa: ANN001
) -> None:
    """Template bindings are always included, series bindings filtered by episode."""
    uow = uow_with_fixtures["uow"]
    series = uow_with_fixtures["series"]
    now = uow_with_fixtures["now"]

    template = await create_episode_template_for_binding_tests(uow, series.id, now)

    bindings = [
        (
            uow_with_fixtures["revision_v1"].id,
            series.id,
            None,
            uow_with_fixtures["episode_early"].id,
        ),
        (
            uow_with_fixtures["revision_v3"].id,
            series.id,
            None,
            uow_with_fixtures["episode_late"].id,
        ),
        (uow_with_fixtures["revision_v2"].id, None, template.id, None),
    ]
    for rev_id, sp_id, tmpl_id, ep_id in bindings:
        await uow.reference_bindings.add(
            ReferenceBinding(
                id=uuid.uuid4(),
                reference_document_revision_id=rev_id,
                target_kind=(
                    ReferenceBindingTargetKind.SERIES_PROFILE
                    if sp_id
                    else ReferenceBindingTargetKind.EPISODE_TEMPLATE
                ),
                series_profile_id=sp_id,
                episode_template_id=tmpl_id,
                ingestion_job_id=None,
                effective_from_episode_id=ep_id,
                created_at=now,
            )
        )
    await uow.commit()

    resolved = await resolve_bindings(
        uow,
        series_profile_id=series.id,
        template_id=template.id,
        episode_id=uow_with_fixtures["episode_early"].id,
    )

    assert len(resolved) == 2
    assert {r.revision.id for r in resolved} == {
        uow_with_fixtures["revision_v1"].id,
        uow_with_fixtures["revision_v2"].id,
    }


async def test_resolve_bindings_template_only(
    uow_with_fixtures,  # noqa: ANN001
) -> None:
    """Template bindings are returned when only template_id is provided."""
    fixtures = uow_with_fixtures
    uow: CanonicalUnitOfWork = fixtures["uow"]
    series = fixtures["series"]
    revision_v2 = fixtures["revision_v2"]
    now = fixtures["now"]

    template = await create_episode_template_for_binding_tests(uow, series.id, now)

    template_binding = ReferenceBinding(
        id=uuid.uuid4(),
        reference_document_revision_id=revision_v2.id,
        target_kind=ReferenceBindingTargetKind.EPISODE_TEMPLATE,
        series_profile_id=None,
        episode_template_id=template.id,
        ingestion_job_id=None,
        effective_from_episode_id=None,
        created_at=now,
    )
    await uow.reference_bindings.add(template_binding)
    await uow.commit()

    resolved = await resolve_bindings(
        uow, series_profile_id=series.id, template_id=template.id
    )

    assert len(resolved) == 1
    assert resolved[0].revision.id == revision_v2.id
    assert resolved[0].binding.id == template_binding.id
