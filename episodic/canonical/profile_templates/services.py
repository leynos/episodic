"""Public application services for profile/template lifecycle operations."""

from __future__ import annotations

import dataclasses as dc
import datetime as dt
import typing as typ
import uuid

from episodic.canonical.domain import (
    EpisodeTemplate,
    EpisodeTemplateHistoryEntry,
    SeriesProfile,
    SeriesProfileHistoryEntry,
)

from .helpers import (
    _get_entity_with_latest_revision,
    _list_history_generic,
    _profile_snapshot,
    _template_snapshot,
    _update_versioned_entity,
    _with_latest_revisions,
)
from .types import (
    AuditMetadata,
    EntityKind,
    EntityNotFoundError,
    EpisodeTemplateData,
    SeriesProfileCreateData,
    UpdateEpisodeTemplateRequest,
    UpdateSeriesProfileRequest,
    _EpisodeTemplateHistoryRepository,
    _EpisodeTemplateRepository,
    _SeriesProfileHistoryRepository,
    _SeriesProfileRepository,
)

if typ.TYPE_CHECKING:
    from episodic.canonical.ports import CanonicalUnitOfWork


def _get_repos_for_kind(
    uow: CanonicalUnitOfWork,
    kind: EntityKind | str,
) -> tuple[
    _SeriesProfileRepository | _EpisodeTemplateRepository,
    _SeriesProfileHistoryRepository | _EpisodeTemplateHistoryRepository,
    str,
]:
    """Resolve repositories and a human label for a specific entity kind."""
    match kind:
        case EntityKind.SERIES_PROFILE | "series_profile":
            return (
                uow.series_profiles,
                uow.series_profile_history,
                "Series profile",
            )
        case EntityKind.EPISODE_TEMPLATE | "episode_template":
            return (
                uow.episode_templates,
                uow.episode_template_history,
                "Episode template",
            )
        case _:
            msg = f"Unsupported kind: {kind}"
            raise ValueError(msg)


async def get_entity_with_revision(
    uow: CanonicalUnitOfWork,
    *,
    entity_id: uuid.UUID,
    kind: EntityKind | str,
) -> tuple[object, int]:
    """Fetch one entity and its latest revision for the requested kind."""
    entity_repo, history_repo, human_label = _get_repos_for_kind(uow, kind)
    match kind:
        case EntityKind.SERIES_PROFILE | "series_profile":
            profile_repo = typ.cast("_SeriesProfileRepository", entity_repo)
            profile_history_repo = typ.cast(
                "_SeriesProfileHistoryRepository",
                history_repo,
            )
            return await _get_entity_with_latest_revision(
                entity_id=entity_id,
                entity_label=human_label,
                get_entity=profile_repo.get,
                fetch_latest=profile_history_repo.get_latest_for_profile,
            )
        case EntityKind.EPISODE_TEMPLATE | "episode_template":
            template_repo = typ.cast("_EpisodeTemplateRepository", entity_repo)
            template_history_repo = typ.cast(
                "_EpisodeTemplateHistoryRepository",
                history_repo,
            )
            return await _get_entity_with_latest_revision(
                entity_id=entity_id,
                entity_label=human_label,
                get_entity=template_repo.get,
                fetch_latest=template_history_repo.get_latest_for_template,
            )
        case _:
            msg = f"Unsupported kind: {kind}"
            raise ValueError(msg)


async def list_history(
    uow: CanonicalUnitOfWork,
    *,
    parent_id: uuid.UUID,
    kind: EntityKind | str,
) -> list[object]:
    """List history entries for the requested entity kind."""
    _, history_repo, _ = _get_repos_for_kind(uow, kind)
    match kind:
        case EntityKind.SERIES_PROFILE | "series_profile":
            profile_history_repo = typ.cast(
                "_SeriesProfileHistoryRepository",
                history_repo,
            )
            items = await _list_history_generic(
                profile_history_repo.list_for_profile,
                parent_id=parent_id,
            )
            return typ.cast("list[object]", items)
        case EntityKind.EPISODE_TEMPLATE | "episode_template":
            template_history_repo = typ.cast(
                "_EpisodeTemplateHistoryRepository",
                history_repo,
            )
            items = await _list_history_generic(
                template_history_repo.list_for_template,
                parent_id=parent_id,
            )
            return typ.cast("list[object]", items)
        case _:
            msg = f"Unsupported kind: {kind}"
            raise ValueError(msg)


async def list_entities_with_revisions(  # noqa: PLR0914  # TODO(@episodic-dev): https://github.com/leynos/episodic/issues/1234 keep explicit branching for per-kind repository wiring
    uow: CanonicalUnitOfWork,
    *,
    kind: EntityKind | str,
    series_profile_id: uuid.UUID | None = None,
) -> list[tuple[object, int]]:
    """List entities with current revisions for the requested kind."""
    entity_repo, history_repo, _ = _get_repos_for_kind(uow, kind)
    match kind:
        case EntityKind.SERIES_PROFILE | "series_profile":
            profile_repo = typ.cast("_SeriesProfileRepository", entity_repo)
            profile_history_repo = typ.cast(
                "_SeriesProfileHistoryRepository",
                history_repo,
            )
            profiles = await profile_repo.list()
            items = await _with_latest_revisions(
                profiles,
                profile_history_repo.get_latest_revisions_for_profiles,
            )
            return typ.cast("list[tuple[object, int]]", items)
        case EntityKind.EPISODE_TEMPLATE | "episode_template":
            template_repo = typ.cast("_EpisodeTemplateRepository", entity_repo)
            template_history_repo = typ.cast(
                "_EpisodeTemplateHistoryRepository",
                history_repo,
            )
            templates = await template_repo.list(series_profile_id)
            items = await _with_latest_revisions(
                templates,
                template_history_repo.get_latest_revisions_for_templates,
            )
            return typ.cast("list[tuple[object, int]]", items)
        case _:
            msg = f"Unsupported kind: {kind}"
            raise ValueError(msg)


async def get_series_profile(
    uow: CanonicalUnitOfWork,
    *,
    profile_id: uuid.UUID,
) -> tuple[SeriesProfile, int]:
    """Fetch one series profile and its latest revision."""
    entity, revision = await get_entity_with_revision(
        uow,
        entity_id=profile_id,
        kind="series_profile",
    )
    return typ.cast("SeriesProfile", entity), revision


async def list_series_profiles(
    uow: CanonicalUnitOfWork,
) -> list[tuple[SeriesProfile, int]]:
    """List series profiles with latest revisions."""
    items = await list_entities_with_revisions(uow, kind="series_profile")
    return [(typ.cast("SeriesProfile", entity), revision) for entity, revision in items]


async def list_series_profile_history(
    uow: CanonicalUnitOfWork,
    *,
    profile_id: uuid.UUID,
) -> list[SeriesProfileHistoryEntry]:
    """List history entries for one series profile."""
    items = await list_history(uow, parent_id=profile_id, kind="series_profile")
    return typ.cast("list[SeriesProfileHistoryEntry]", items)


async def get_episode_template(
    uow: CanonicalUnitOfWork,
    *,
    template_id: uuid.UUID,
) -> tuple[EpisodeTemplate, int]:
    """Fetch one episode template and its latest revision."""
    entity, revision = await get_entity_with_revision(
        uow,
        entity_id=template_id,
        kind="episode_template",
    )
    return typ.cast("EpisodeTemplate", entity), revision


async def list_episode_templates(
    uow: CanonicalUnitOfWork,
    *,
    series_profile_id: uuid.UUID | None = None,
) -> list[tuple[EpisodeTemplate, int]]:
    """List episode templates with latest revisions."""
    items = await list_entities_with_revisions(
        uow,
        kind="episode_template",
        series_profile_id=series_profile_id,
    )
    return [
        (typ.cast("EpisodeTemplate", entity), revision) for entity, revision in items
    ]


async def list_episode_template_history(
    uow: CanonicalUnitOfWork,
    *,
    template_id: uuid.UUID,
) -> list[EpisodeTemplateHistoryEntry]:
    """List history entries for one episode template."""
    items = await list_history(uow, parent_id=template_id, kind="episode_template")
    return typ.cast("list[EpisodeTemplateHistoryEntry]", items)


async def create_series_profile(
    uow: CanonicalUnitOfWork,
    *,
    data: SeriesProfileCreateData,
    audit: AuditMetadata,
) -> tuple[SeriesProfile, int]:
    """Create a series profile and initial history entry."""
    now = dt.datetime.now(dt.UTC)
    profile = SeriesProfile(
        id=uuid.uuid4(),
        slug=data.slug,
        title=data.title,
        description=data.description,
        configuration=data.configuration,
        created_at=now,
        updated_at=now,
    )
    history_entry = SeriesProfileHistoryEntry(
        id=uuid.uuid4(),
        series_profile_id=profile.id,
        revision=1,
        actor=audit.actor,
        note=audit.note,
        snapshot=_profile_snapshot(profile),
        created_at=now,
    )
    await uow.series_profiles.add(profile)
    await uow.flush()
    await uow.series_profile_history.add(history_entry)
    await uow.commit()
    return profile, 1


async def update_series_profile(
    uow: CanonicalUnitOfWork,
    *,
    request: UpdateSeriesProfileRequest,
) -> tuple[SeriesProfile, int]:
    """Update a series profile with optimistic-lock revision checks."""
    return await _update_versioned_entity(
        uow,
        entity_id=request.profile_id,
        expected_revision=request.expected_revision,
        entity_label="Series profile",
        entity_repo=uow.series_profiles,
        history_repo=uow.series_profile_history,
        fetch_latest=uow.series_profile_history.get_latest_for_profile,
        history_entry_class=SeriesProfileHistoryEntry,
        entity_id_field="series_profile_id",
        update_fields=lambda entity, now: dc.replace(
            entity,
            title=request.data.title,
            description=request.data.description,
            configuration=request.data.configuration,
            updated_at=now,
        ),
        create_snapshot=_profile_snapshot,
        audit=request.audit,
    )


async def create_episode_template(
    uow: CanonicalUnitOfWork,
    *,
    series_profile_id: uuid.UUID,
    data: EpisodeTemplateData,
) -> tuple[EpisodeTemplate, int]:
    """Create an episode template and initial history entry."""
    profile = await uow.series_profiles.get(series_profile_id)
    if profile is None:
        msg = f"Series profile {series_profile_id} not found."
        raise EntityNotFoundError(msg)

    now = dt.datetime.now(dt.UTC)
    template = EpisodeTemplate(
        id=uuid.uuid4(),
        series_profile_id=series_profile_id,
        slug=data.slug,
        title=data.title,
        description=data.description,
        structure=data.structure,
        created_at=now,
        updated_at=now,
    )
    history_entry = EpisodeTemplateHistoryEntry(
        id=uuid.uuid4(),
        episode_template_id=template.id,
        revision=1,
        actor=data.actor,
        note=data.note,
        snapshot=_template_snapshot(template),
        created_at=now,
    )
    await uow.episode_templates.add(template)
    await uow.flush()
    await uow.episode_template_history.add(history_entry)
    await uow.commit()
    return template, 1


async def update_episode_template(
    uow: CanonicalUnitOfWork,
    *,
    request: UpdateEpisodeTemplateRequest,
) -> tuple[EpisodeTemplate, int]:
    """Update an episode template with optimistic-lock revision checks."""
    return await _update_versioned_entity(
        uow,
        entity_id=request.template_id,
        expected_revision=request.expected_revision,
        entity_label="Episode template",
        entity_repo=uow.episode_templates,
        history_repo=uow.episode_template_history,
        fetch_latest=uow.episode_template_history.get_latest_for_template,
        history_entry_class=EpisodeTemplateHistoryEntry,
        entity_id_field="episode_template_id",
        update_fields=lambda entity, now: dc.replace(
            entity,
            title=request.fields.title,
            description=request.fields.description,
            structure=request.fields.structure,
            updated_at=now,
        ),
        create_snapshot=_template_snapshot,
        audit=request.audit,
    )
