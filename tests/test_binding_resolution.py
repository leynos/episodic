"""Unit tests for reference binding resolution algorithm."""

import datetime as dt
import typing as typ
import uuid

import pytest

from episodic.canonical.domain import (
    ReferenceBinding,
    ReferenceBindingTargetKind,
)
from episodic.canonical.reference_documents.resolution import (
    ResolvedBinding,
    resolve_bindings,
)

if typ.TYPE_CHECKING:
    from episodic.canonical.unit_of_work_protocols import CanonicalUnitOfWork
    from tests.fixtures.binding import BindingFixtures

from tests.conftest import create_episode_template_for_binding_tests

pytestmark = [pytest.mark.asyncio]


async def test_resolve_bindings_returns_empty_when_no_bindings_exist(
    uow_with_fixtures: BindingFixtures,
) -> None:
    """Resolution returns empty list when no bindings exist for series profile."""
    fixtures = uow_with_fixtures
    uow: CanonicalUnitOfWork = fixtures["uow"]
    series = fixtures["series"]

    resolved = await resolve_bindings(uow, series_profile_id=series.id)

    assert resolved == [], "must match"


async def test_resolve_bindings_returns_empty_for_nonexistent_episode_id(
    uow_with_fixtures: BindingFixtures,
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

    assert resolved == [], "must match"


async def test_resolve_bindings_returns_default_binding_when_no_episode_context(
    uow_with_fixtures: BindingFixtures,
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

    assert len(resolved) == 1, "must match"
    assert isinstance(resolved[0], ResolvedBinding), "must have required type"
    assert resolved[0].binding.id == binding.id, "must match"
    assert resolved[0].revision.id == revision_v1.id, "must match"


async def test_resolve_bindings_selects_latest_applicable_episode_binding(  # noqa: PLR0914  # The scenario keeps distinct intermediate values for readable behavioural assertions.
    uow_with_fixtures: BindingFixtures,
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

    resolution_cases = (
        (episode_early, binding_early, revision_v1),
        (episode_middle, binding_middle, revision_v2),
        (episode_late, binding_late, revision_v3),
    )
    for episode, binding, revision in resolution_cases:
        resolved = await resolve_bindings(
            uow, series_profile_id=series.id, episode_id=episode.id
        )
        assert len(resolved) == 1, "each context must resolve one binding"
        assert resolved[0].binding.id == binding.id, "binding must match context"
        assert resolved[0].revision.id == revision.id, "revision must match context"


async def test_resolve_bindings_excludes_future_episode_bindings(
    uow_with_fixtures: BindingFixtures,
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

    assert resolved == [], "must match"


async def test_resolve_bindings_includes_template_bindings(
    uow_with_fixtures: BindingFixtures,
) -> None:
    """Template bindings are included when template_id is provided."""
    uow = uow_with_fixtures["uow"]
    series = uow_with_fixtures["series"]
    now = uow_with_fixtures["now"]

    template = await create_episode_template_for_binding_tests(uow, series.id, now)

    for revision, kind, tmpl_id in [
        (
            uow_with_fixtures["revision_v1"],
            ReferenceBindingTargetKind.SERIES_PROFILE,
            None,
        ),
        (
            uow_with_fixtures["revision_v2"],
            ReferenceBindingTargetKind.EPISODE_TEMPLATE,
            template.id,
        ),
    ]:
        await uow.reference_bindings.add(
            ReferenceBinding(
                id=uuid.uuid4(),
                reference_document_revision_id=revision.id,
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

    assert len(resolved) == 2, "must match"
    resolved_revision_ids = {r.revision.id for r in resolved}
    assert resolved_revision_ids == {
        uow_with_fixtures["revision_v1"].id,
        uow_with_fixtures["revision_v2"].id,
    }, "must match"


async def test_resolve_bindings_merges_template_with_episode(
    uow_with_fixtures: BindingFixtures,
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

    assert len(resolved) == 2, "must match"
    assert {r.revision.id for r in resolved} == {
        uow_with_fixtures["revision_v1"].id,
        uow_with_fixtures["revision_v2"].id,
    }, "must contain"


async def test_resolve_bindings_template_only(
    uow_with_fixtures: BindingFixtures,
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

    assert len(resolved) == 1, "must match"
    assert resolved[0].revision.id == revision_v2.id, "must match"
    assert resolved[0].binding.id == template_binding.id, "must match"
