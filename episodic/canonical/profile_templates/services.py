"""Public services for profile/template lifecycle operations.

This module exposes canonical application services used by API/resource
adapters to create, update, retrieve, and list profiles/templates with revision
metadata. Most functions return ``(entity, revision)`` pairs or history lists
and raise typed domain errors for missing entities or revision conflicts.

Examples
--------
>>> profile, revision = await create_series_profile(uow, data=data, audit=audit)
>>> template, rev = await get_episode_template(uow, template_id=template_id)
"""

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
    """Fetch one entity and its latest persisted revision.

    Parameters
    ----------
    uow : CanonicalUnitOfWork
        Unit-of-work providing repositories and transactional boundaries.
    entity_id : uuid.UUID
        Identifier of the entity to fetch.
    kind : EntityKind | str
        Entity kind selector (series profile or episode template).

    Returns
    -------
    tuple[object, int]
        Tuple of the loaded entity object and its latest revision number.

    Raises
    ------
    EntityNotFoundError
        Raised when the requested entity does not exist.
    ValueError
        Raised when ``kind`` is unsupported.
    """
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
    """List history entries for one parent entity.

    Parameters
    ----------
    uow : CanonicalUnitOfWork
        Unit-of-work providing repositories and transactional boundaries.
    parent_id : uuid.UUID
        Identifier of the parent entity.
    kind : EntityKind | str
        Entity kind selector (series profile or episode template).

    Returns
    -------
    list[object]
        History entries for the requested parent entity.

    Raises
    ------
    ValueError
        Raised when ``kind`` is unsupported.
    """
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
    """List entities paired with their latest revisions.

    Parameters
    ----------
    uow : CanonicalUnitOfWork
        Unit-of-work providing repositories and transactional boundaries.
    kind : EntityKind | str
        Entity kind selector (series profile or episode template).
    series_profile_id : uuid.UUID | None, default None
        Optional profile filter used for episode-template listing.

    Returns
    -------
    list[tuple[object, int]]
        Sequence of ``(entity, latest_revision)`` pairs.

    Raises
    ------
    ValueError
        Raised when ``kind`` is unsupported.
    """
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
    """Fetch one series profile and its latest revision.

    Parameters
    ----------
    uow : CanonicalUnitOfWork
        Unit-of-work providing repositories and transactional boundaries.
    profile_id : uuid.UUID
        Identifier of the profile to load.

    Returns
    -------
    tuple[SeriesProfile, int]
        Loaded profile and latest revision.

    Raises
    ------
    EntityNotFoundError
        Raised when the profile does not exist.
    ValueError
        Raised when delegated kind dispatch is unsupported.
    """
    entity, revision = await get_entity_with_revision(
        uow,
        entity_id=profile_id,
        kind="series_profile",
    )
    return typ.cast("SeriesProfile", entity), revision


async def list_series_profiles(
    uow: CanonicalUnitOfWork,
) -> list[tuple[SeriesProfile, int]]:
    """List all series profiles with latest revisions.

    Parameters
    ----------
    uow : CanonicalUnitOfWork
        Unit-of-work providing repositories and transactional boundaries.

    Returns
    -------
    list[tuple[SeriesProfile, int]]
        Sequence of profile/revision pairs.

    Raises
    ------
    ValueError
        Raised when delegated kind dispatch is unsupported.
    """
    items = await list_entities_with_revisions(uow, kind="series_profile")
    return [(typ.cast("SeriesProfile", entity), revision) for entity, revision in items]


async def list_series_profile_history(
    uow: CanonicalUnitOfWork,
    *,
    profile_id: uuid.UUID,
) -> list[SeriesProfileHistoryEntry]:
    """List history entries for one series profile.

    Parameters
    ----------
    uow : CanonicalUnitOfWork
        Unit-of-work providing repositories and transactional boundaries.
    profile_id : uuid.UUID
        Identifier of the profile whose history is requested.

    Returns
    -------
    list[SeriesProfileHistoryEntry]
        History entries for the given profile.

    Raises
    ------
    ValueError
        Raised when delegated kind dispatch is unsupported.
    """
    items = await list_history(uow, parent_id=profile_id, kind="series_profile")
    return typ.cast("list[SeriesProfileHistoryEntry]", items)


async def get_episode_template(
    uow: CanonicalUnitOfWork,
    *,
    template_id: uuid.UUID,
) -> tuple[EpisodeTemplate, int]:
    """Fetch one episode template and its latest revision.

    Parameters
    ----------
    uow : CanonicalUnitOfWork
        Unit-of-work providing repositories and transactional boundaries.
    template_id : uuid.UUID
        Identifier of the template to load.

    Returns
    -------
    tuple[EpisodeTemplate, int]
        Loaded template and latest revision.

    Raises
    ------
    EntityNotFoundError
        Raised when the template does not exist.
    ValueError
        Raised when delegated kind dispatch is unsupported.
    """
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
    """List episode templates with latest revisions.

    Parameters
    ----------
    uow : CanonicalUnitOfWork
        Unit-of-work providing repositories and transactional boundaries.
    series_profile_id : uuid.UUID | None, default None
        Optional profile filter for template listing.

    Returns
    -------
    list[tuple[EpisodeTemplate, int]]
        Sequence of template/revision pairs.

    Raises
    ------
    ValueError
        Raised when delegated kind dispatch is unsupported.
    """
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
    """List history entries for one episode template.

    Parameters
    ----------
    uow : CanonicalUnitOfWork
        Unit-of-work providing repositories and transactional boundaries.
    template_id : uuid.UUID
        Identifier of the template whose history is requested.

    Returns
    -------
    list[EpisodeTemplateHistoryEntry]
        History entries for the given template.

    Raises
    ------
    ValueError
        Raised when delegated kind dispatch is unsupported.
    """
    items = await list_history(uow, parent_id=template_id, kind="episode_template")
    return typ.cast("list[EpisodeTemplateHistoryEntry]", items)


async def create_series_profile(
    uow: CanonicalUnitOfWork,
    *,
    data: SeriesProfileCreateData,
    audit: AuditMetadata,
) -> tuple[SeriesProfile, int]:
    """Create a series profile and initial history entry.

    Parameters
    ----------
    uow : CanonicalUnitOfWork
        Unit-of-work providing repositories and transactional boundaries.
    data : SeriesProfileCreateData
        Input data for the new profile.
    audit : AuditMetadata
        Actor metadata recorded in the initial history entry.

    Returns
    -------
    tuple[SeriesProfile, int]
        Created profile and initial revision (``1``).
    """
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
    """Update a series profile with optimistic-lock checks.

    Parameters
    ----------
    uow : CanonicalUnitOfWork
        Unit-of-work providing repositories and transactional boundaries.
    request : UpdateSeriesProfileRequest
        Typed update request containing target id, expected revision, updated
        fields, and audit metadata.

    Returns
    -------
    tuple[SeriesProfile, int]
        Updated profile and the next revision number.

    Raises
    ------
    EntityNotFoundError
        Raised when the profile does not exist.
    RevisionConflictError
        Raised when expected and latest revisions do not match.
    """
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
    """Create an episode template and initial history entry.

    Parameters
    ----------
    uow : CanonicalUnitOfWork
        Unit-of-work providing repositories and transactional boundaries.
    series_profile_id : uuid.UUID
        Identifier of the parent series profile.
    data : EpisodeTemplateData
        Input data for the new template.

    Returns
    -------
    tuple[EpisodeTemplate, int]
        Created template and initial revision (``1``).

    Raises
    ------
    EntityNotFoundError
        Raised when ``series_profile_id`` does not reference an existing
        profile.
    """
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
    """Update an episode template with optimistic-lock checks.

    Parameters
    ----------
    uow : CanonicalUnitOfWork
        Unit-of-work providing repositories and transactional boundaries.
    request : UpdateEpisodeTemplateRequest
        Typed update request containing target id, expected revision, updated
        fields, and audit metadata.

    Returns
    -------
    tuple[EpisodeTemplate, int]
        Updated template and the next revision number.

    Raises
    ------
    EntityNotFoundError
        Raised when the template does not exist.
    RevisionConflictError
        Raised when expected and latest revisions do not match.
    """
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
