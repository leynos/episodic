"""Application services for profile_templates lifecycle operations.

This module provides creation, retrieval, listing, update, and history
management flows for series profiles and episode templates. Each service
coordinates repositories via the canonical unit of work and enforces
optimistic-lock revision rules.

Example
-------
Use ``create_series_profile`` followed by ``list_entities_with_revisions`` to
create and inspect profiles through the ``profile_templates`` service layer.
"""

from __future__ import annotations

import dataclasses as dc
import datetime as dt
import typing as typ
import uuid
from itertools import starmap

from sqlalchemy.exc import IntegrityError

from .domain import (
    EpisodeTemplate,
    EpisodeTemplateHistoryEntry,
    JsonMapping,
    SeriesProfile,
    SeriesProfileHistoryEntry,
)

if typ.TYPE_CHECKING:
    from .ports import CanonicalUnitOfWork


@dc.dataclass(frozen=True, slots=True)
class AuditMetadata:
    """Audit metadata for versioned operations.

    Attributes
    ----------
    actor : str | None
        Optional identifier for the actor performing the operation.
    note : str | None
        Optional free-form note attached to the operation.
    """

    actor: str | None
    note: str | None


@dc.dataclass(frozen=True, slots=True)
class SeriesProfileData:
    """Entity data for series profile operations.

    Attributes
    ----------
    title : str
        Human-readable profile title.
    description : str | None
        Optional longer profile description.
    configuration : JsonMapping
        Profile configuration payload consumed by downstream workflows.
    """

    title: str
    description: str | None
    configuration: JsonMapping


@dc.dataclass(frozen=True, slots=True)
class SeriesProfileCreateData(SeriesProfileData):
    """Entity data for creating a series profile.

    Attributes
    ----------
    slug : str
        Stable profile slug used for unique identification.
    """

    slug: str


@dc.dataclass(frozen=True, slots=True)
class SeriesProfileUpdateFields(SeriesProfileData):
    """Entity data for updating a series profile.

    Attributes
    ----------
    title : str
        Updated profile title.
    description : str | None
        Updated profile description.
    configuration : JsonMapping
        Updated profile configuration payload.
    """


@dc.dataclass(frozen=True, slots=True)
class EpisodeTemplateUpdateFields:
    """Entity data for updating an episode template.

    Attributes
    ----------
    title : str
        Updated template title.
    description : str | None
        Updated template description.
    structure : JsonMapping
        Updated JSON template structure payload.
    """

    title: str
    description: str | None
    structure: JsonMapping


@dc.dataclass(frozen=True, slots=True)
class EpisodeTemplateData:
    """Data for creating or updating an episode template.

    Attributes
    ----------
    slug : str
        Stable slug identifying the template within a profile.
    title : str
        Human-readable template title.
    description : str | None
        Optional longer template description.
    structure : JsonMapping
        JSON structure that defines template segments.
    actor : str | None
        Optional identifier for the actor creating the template.
    note : str | None
        Optional free-form audit note.
    """

    slug: str
    title: str
    description: str | None
    structure: JsonMapping
    actor: str | None
    note: str | None


@dc.dataclass(frozen=True, slots=True)
class UpdateSeriesProfileRequest:
    """Request to update a series profile with optimistic locking.

    Attributes
    ----------
    profile_id : uuid.UUID
        Identifier of the profile to update.
    expected_revision : int
        Revision expected by the caller for optimistic locking.
    data : SeriesProfileData
        Updated profile field values.
    audit : AuditMetadata
        Actor metadata captured for history tracking.
    """

    profile_id: uuid.UUID
    expected_revision: int
    data: SeriesProfileData
    audit: AuditMetadata


@dc.dataclass(frozen=True, slots=True)
class UpdateEpisodeTemplateRequest:
    """Request to update an episode template with optimistic locking.

    Attributes
    ----------
    template_id : uuid.UUID
        Identifier of the template to update.
    expected_revision : int
        Revision expected by the caller for optimistic locking.
    fields : EpisodeTemplateUpdateFields
        Updated template field values.
    audit : AuditMetadata
        Actor metadata captured for history tracking.
    """

    template_id: uuid.UUID
    expected_revision: int
    fields: EpisodeTemplateUpdateFields
    audit: AuditMetadata


class EntityNotFoundError(LookupError):
    """Raised when an expected profile or template does not exist."""


class RevisionConflictError(ValueError):
    """Raised when optimistic-lock revision preconditions are not met."""


EntityKind = typ.Literal["series_profile", "episode_template"]


class _RevisionedEntry(typ.Protocol):
    """Protocol for history entries that expose a revision."""

    revision: int


class _VersionedEntity(typ.Protocol):
    """Protocol for versioned entities with stable identifiers."""

    id: uuid.UUID


class _EntityRepository[EntityT: _VersionedEntity](typ.Protocol):
    """Protocol for repositories that update versioned entities."""

    async def get(self, entity_id: uuid.UUID, /) -> EntityT | None: ...

    async def update(self, entity: EntityT, /) -> None: ...


class _HistoryRepository[HistoryT](typ.Protocol):
    """Protocol for repositories that persist history entries."""

    async def add(self, entry: HistoryT, /) -> None: ...


class _SeriesProfileRepository(typ.Protocol):
    """Protocol for series-profile repository read operations."""

    async def get(self, entity_id: uuid.UUID, /) -> SeriesProfile | None: ...

    async def list(self) -> typ.Sequence[SeriesProfile]: ...


class _EpisodeTemplateRepository(typ.Protocol):
    """Protocol for episode-template repository read operations."""

    async def get(self, entity_id: uuid.UUID, /) -> EpisodeTemplate | None: ...

    async def list(
        self, series_profile_id: uuid.UUID | None
    ) -> typ.Sequence[EpisodeTemplate]: ...


class _SeriesProfileHistoryRepository(typ.Protocol):
    """Protocol for series-profile history repository read operations."""

    async def get_latest_for_profile(
        self,
        profile_id: uuid.UUID,
        /,
    ) -> SeriesProfileHistoryEntry | None: ...

    async def list_for_profile(
        self,
        profile_id: uuid.UUID,
        /,
    ) -> list[SeriesProfileHistoryEntry]: ...

    async def get_latest_revisions_for_profiles(
        self,
        profile_ids: typ.Collection[uuid.UUID],
        /,
    ) -> dict[uuid.UUID, int]: ...


class _EpisodeTemplateHistoryRepository(typ.Protocol):
    """Protocol for episode-template history repository read operations."""

    async def get_latest_for_template(
        self,
        template_id: uuid.UUID,
        /,
    ) -> EpisodeTemplateHistoryEntry | None: ...

    async def list_for_template(
        self,
        template_id: uuid.UUID,
        /,
    ) -> list[EpisodeTemplateHistoryEntry]: ...

    async def get_latest_revisions_for_templates(
        self,
        template_ids: typ.Collection[uuid.UUID],
        /,
    ) -> dict[uuid.UUID, int]: ...


async def _get_latest_revision[HistoryEntryT: _RevisionedEntry](
    fetch_latest: typ.Callable[
        [uuid.UUID],
        typ.Awaitable[HistoryEntryT | None],
    ],
    entity_id: uuid.UUID,
) -> int:
    """Return the latest persisted revision for an entity."""
    latest = await fetch_latest(entity_id)
    return 0 if latest is None else latest.revision


def _check_revision_conflict(
    *,
    expected_revision: int,
    latest_revision: int,
    entity_label: str,
) -> None:
    """Raise when optimistic-lock revisions do not match."""
    if expected_revision != latest_revision:
        msg = (
            f"{entity_label} revision conflict: expected "
            f"{expected_revision}, found {latest_revision}."
        )
        raise RevisionConflictError(msg)


def _is_revision_conflict_integrity_error(
    exc: IntegrityError,
    entity_id_field: str,
) -> bool:
    """Return True when an integrity error indicates a revision collision.

    Constraint-name markers below are coupled to history uniqueness constraints
    in ``episodic/canonical/storage/models.py``.
    """
    detail = str(getattr(exc, "orig", exc))
    return any(
        marker in detail
        for marker in (
            "uq_series_profile_history_revision",
            "uq_episode_template_history_revision",
            f"({entity_id_field}, revision)",
            f"{entity_id_field}, revision",
        )
    )


def _build_snapshot_base(
    *,
    entity_id: uuid.UUID,
    created_at: dt.datetime,
    updated_at: dt.datetime,
) -> JsonMapping:
    """Build shared snapshot fields."""
    return {
        "id": str(entity_id),
        "created_at": created_at.isoformat(),
        "updated_at": updated_at.isoformat(),
    }


async def _get_entity_with_latest_revision[EntityT: _VersionedEntity](
    *,
    entity_id: uuid.UUID,
    entity_label: str,
    get_entity: typ.Callable[[uuid.UUID], typ.Awaitable[EntityT | None]],
    fetch_latest: typ.Callable[[uuid.UUID], typ.Awaitable[_RevisionedEntry | None]],
) -> tuple[EntityT, int]:
    """Return an entity with its latest revision or raise if absent."""
    entity = await get_entity(entity_id)
    if entity is None:
        msg = f"{entity_label} {entity_id} not found."
        raise EntityNotFoundError(msg)
    revision = await _get_latest_revision(fetch_latest, entity_id)
    return entity, revision


async def _list_history_generic[HistoryT](
    list_for_parent: typ.Callable[[uuid.UUID], typ.Awaitable[list[HistoryT]]],
    *,
    parent_id: uuid.UUID,
) -> list[HistoryT]:
    """List history entries for a parent entity."""
    return await list_for_parent(parent_id)


async def _with_latest_revisions[EntityT: _VersionedEntity](
    entities: typ.Sequence[EntityT],
    fetch_bulk_revisions: typ.Callable[
        [typ.Collection[uuid.UUID]],
        typ.Awaitable[dict[uuid.UUID, int]],
    ],
) -> list[tuple[EntityT, int]]:
    """Pair entities with their latest revision values."""
    entity_ids = [entity.id for entity in entities]
    revisions = await fetch_bulk_revisions(entity_ids)
    return [(entity, revisions.get(entity.id, 0)) for entity in entities]


def _get_repos_for_kind(
    uow: CanonicalUnitOfWork,
    kind: EntityKind,
) -> tuple[
    _SeriesProfileRepository | _EpisodeTemplateRepository,
    _SeriesProfileHistoryRepository | _EpisodeTemplateHistoryRepository,
    str,
]:
    """Resolve repositories and a human label for a specific entity kind."""
    if kind == "series_profile":
        return (
            uow.series_profiles,
            uow.series_profile_history,
            "Series profile",
        )
    return (
        uow.episode_templates,
        uow.episode_template_history,
        "Episode template",
    )


async def get_entity_with_revision(
    uow: CanonicalUnitOfWork,
    *,
    entity_id: uuid.UUID,
    kind: EntityKind,
) -> tuple[object, int]:
    """Fetch one entity and its latest revision for the requested kind."""
    entity_repo, history_repo, human_label = _get_repos_for_kind(uow, kind)
    if kind == "series_profile":
        profile_repo = typ.cast("_SeriesProfileRepository", entity_repo)
        profile_history_repo = typ.cast("_SeriesProfileHistoryRepository", history_repo)
        return await _get_entity_with_latest_revision(
            entity_id=entity_id,
            entity_label=human_label,
            get_entity=profile_repo.get,
            fetch_latest=profile_history_repo.get_latest_for_profile,
        )

    template_repo = typ.cast("_EpisodeTemplateRepository", entity_repo)
    template_history_repo = typ.cast("_EpisodeTemplateHistoryRepository", history_repo)
    return await _get_entity_with_latest_revision(
        entity_id=entity_id,
        entity_label=human_label,
        get_entity=template_repo.get,
        fetch_latest=template_history_repo.get_latest_for_template,
    )


async def list_history(
    uow: CanonicalUnitOfWork,
    *,
    parent_id: uuid.UUID,
    kind: EntityKind,
) -> list[object]:
    """List history entries for the requested entity kind."""
    _, history_repo, _ = _get_repos_for_kind(uow, kind)
    if kind == "series_profile":
        profile_history_repo = typ.cast("_SeriesProfileHistoryRepository", history_repo)
        items = await _list_history_generic(
            profile_history_repo.list_for_profile,
            parent_id=parent_id,
        )
        return typ.cast("list[object]", items)

    template_history_repo = typ.cast("_EpisodeTemplateHistoryRepository", history_repo)
    items = await _list_history_generic(
        template_history_repo.list_for_template,
        parent_id=parent_id,
    )
    return typ.cast("list[object]", items)


async def list_entities_with_revisions(
    uow: CanonicalUnitOfWork,
    *,
    kind: EntityKind,
    series_profile_id: uuid.UUID | None = None,
) -> list[tuple[object, int]]:
    """List entities with current revisions for the requested kind."""
    entity_repo, history_repo, _ = _get_repos_for_kind(uow, kind)
    if kind == "series_profile":
        profile_repo = typ.cast("_SeriesProfileRepository", entity_repo)
        profile_history_repo = typ.cast("_SeriesProfileHistoryRepository", history_repo)
        profiles = await profile_repo.list()
        items = await _with_latest_revisions(
            profiles,
            profile_history_repo.get_latest_revisions_for_profiles,
        )
        return typ.cast("list[tuple[object, int]]", items)

    template_repo = typ.cast("_EpisodeTemplateRepository", entity_repo)
    template_history_repo = typ.cast("_EpisodeTemplateHistoryRepository", history_repo)
    templates = await template_repo.list(series_profile_id)
    items = await _with_latest_revisions(
        templates,
        template_history_repo.get_latest_revisions_for_templates,
    )
    return typ.cast("list[tuple[object, int]]", items)


async def _update_versioned_entity[EntityT: _VersionedEntity, HistoryT](  # noqa: PLR0913  # Context: https://github.com/leynos/episodic/pull/25
    uow: CanonicalUnitOfWork,
    *,
    entity_id: uuid.UUID,
    expected_revision: int,
    entity_label: str,
    entity_repo: _EntityRepository[EntityT],
    history_repo: _HistoryRepository[HistoryT],
    fetch_latest: typ.Callable[[uuid.UUID], typ.Awaitable[_RevisionedEntry | None]],
    history_entry_class: type[HistoryT],
    entity_id_field: str,
    update_fields: typ.Callable[[EntityT, dt.datetime], EntityT],
    create_snapshot: typ.Callable[[EntityT], JsonMapping],
    audit: AuditMetadata,
) -> tuple[EntityT, int]:
    """Update a versioned entity using optimistic locking."""
    entity = await entity_repo.get(entity_id)
    if entity is None:
        msg = f"{entity_label} {entity_id} not found."
        raise EntityNotFoundError(msg)

    latest_revision = await _get_latest_revision(fetch_latest, entity_id)
    _check_revision_conflict(
        expected_revision=expected_revision,
        latest_revision=latest_revision,
        entity_label=entity_label,
    )

    now = dt.datetime.now(dt.UTC)
    updated_entity = update_fields(entity, now)
    next_revision = latest_revision + 1
    history_entry = history_entry_class(
        id=uuid.uuid4(),
        revision=next_revision,
        actor=audit.actor,
        note=audit.note,
        snapshot=create_snapshot(updated_entity),
        created_at=now,
        **{entity_id_field: updated_entity.id},
    )
    try:
        await entity_repo.update(updated_entity)
        await history_repo.add(history_entry)
        await uow.commit()
    except IntegrityError as exc:
        await uow.rollback()
        if not _is_revision_conflict_integrity_error(exc, entity_id_field):
            raise
        msg = f"{entity_label} revision conflict: concurrent update detected."
        raise RevisionConflictError(msg) from exc
    return updated_entity, next_revision


def _profile_snapshot(profile: SeriesProfile) -> JsonMapping:
    """Return a stable JSON snapshot for profile history."""
    return {
        **_build_snapshot_base(
            entity_id=profile.id,
            created_at=profile.created_at,
            updated_at=profile.updated_at,
        ),
        "slug": profile.slug,
        "title": profile.title,
        "description": profile.description,
        "configuration": profile.configuration,
    }


def _template_snapshot(template: EpisodeTemplate) -> JsonMapping:
    """Return a stable JSON snapshot for template history."""
    return {
        **_build_snapshot_base(
            entity_id=template.id,
            created_at=template.created_at,
            updated_at=template.updated_at,
        ),
        "series_profile_id": str(template.series_profile_id),
        "slug": template.slug,
        "title": template.title,
        "description": template.description,
        "structure": template.structure,
    }


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
        Active unit of work providing repository access.
    data : SeriesProfileCreateData
        Profile values used to create the entity.
    audit : AuditMetadata
        Actor metadata recorded in history.

    Returns
    -------
    tuple[SeriesProfile, int]
        Persisted profile and initial revision value ``1``.
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
    """Update a series profile with optimistic-lock revision checks.

    Parameters
    ----------
    uow : CanonicalUnitOfWork
        Active unit of work providing repository access.
    request : UpdateSeriesProfileRequest
        Update request containing target ID, expected revision, and fields.

    Returns
    -------
    tuple[SeriesProfile, int]
        Updated profile and its new revision number.

    Raises
    ------
    EntityNotFoundError
        Raised when the target profile does not exist.
    RevisionConflictError
        Raised when optimistic-lock preconditions fail.
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
        Active unit of work providing repository access.
    series_profile_id : uuid.UUID
        Identifier of the owning series profile.
    data : EpisodeTemplateData
        Template values used to create the entity.

    Returns
    -------
    tuple[EpisodeTemplate, int]
        Persisted template and initial revision value ``1``.

    Raises
    ------
    EntityNotFoundError
        Raised when the owning series profile does not exist.
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
    """Update an episode template with optimistic-lock revision checks.

    Parameters
    ----------
    uow : CanonicalUnitOfWork
        Active unit of work providing repository access.
    request : UpdateEpisodeTemplateRequest
        Update request containing target ID, expected revision, and fields.

    Returns
    -------
    tuple[EpisodeTemplate, int]
        Updated template and its new revision number.

    Raises
    ------
    EntityNotFoundError
        Raised when the target template does not exist.
    RevisionConflictError
        Raised when optimistic-lock preconditions fail.
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


def _serialize_profile_for_brief(
    profile: SeriesProfile,
    revision: int,
) -> JsonMapping:
    """Serialize profile with revision for structured brief payloads."""
    return {
        "id": str(profile.id),
        "slug": profile.slug,
        "title": profile.title,
        "description": profile.description,
        "configuration": profile.configuration,
        "revision": revision,
        "updated_at": profile.updated_at.isoformat(),
    }


def _serialize_template_for_brief(
    template: EpisodeTemplate,
    revision: int,
) -> JsonMapping:
    """Serialize episode template with revision for structured brief payloads."""
    return {
        "id": str(template.id),
        "series_profile_id": str(template.series_profile_id),
        "slug": template.slug,
        "title": template.title,
        "description": template.description,
        "structure": template.structure,
        "revision": revision,
        "updated_at": template.updated_at.isoformat(),
    }


async def _load_template_items_for_brief(
    uow: CanonicalUnitOfWork,
    *,
    profile_id: uuid.UUID,
    template_id: uuid.UUID | None,
) -> list[tuple[EpisodeTemplate, int]]:
    """Load template and revision pairs for structured brief rendering."""
    if template_id is None:
        items = await list_entities_with_revisions(
            uow,
            kind="episode_template",
            series_profile_id=profile_id,
        )
        return [
            (typ.cast("EpisodeTemplate", template), revision)
            for template, revision in items
        ]

    template_obj, template_revision = await get_entity_with_revision(
        uow,
        entity_id=template_id,
        kind="episode_template",
    )
    template = typ.cast("EpisodeTemplate", template_obj)
    if template.series_profile_id != profile_id:
        msg = (
            f"Episode template {template.id} does not belong to "
            f"series profile {profile_id}."
        )
        raise EntityNotFoundError(msg)
    return [(template, template_revision)]


async def build_series_brief(
    uow: CanonicalUnitOfWork,
    *,
    profile_id: uuid.UUID,
    template_id: uuid.UUID | None,
) -> JsonMapping:
    """Build a structured brief payload for downstream generators.

    Parameters
    ----------
    uow : CanonicalUnitOfWork
        Active unit of work providing repository access.
    profile_id : uuid.UUID
        Identifier of the series profile to include in the brief.
    template_id : uuid.UUID | None
        Optional template identifier to scope the brief to one template.

    Returns
    -------
    JsonMapping
        Structured payload containing profile and template data with revisions.

    Raises
    ------
    EntityNotFoundError
        Raised when the profile or requested template does not exist, or when
        the template does not belong to the profile.
    """
    profile_obj, profile_revision = await get_entity_with_revision(
        uow,
        entity_id=profile_id,
        kind="series_profile",
    )
    profile = typ.cast("SeriesProfile", profile_obj)
    template_items = await _load_template_items_for_brief(
        uow,
        profile_id=profile.id,
        template_id=template_id,
    )

    return {
        "series_profile": _serialize_profile_for_brief(profile, profile_revision),
        "episode_templates": list(
            starmap(_serialize_template_for_brief, template_items)
        ),
    }
