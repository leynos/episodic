"""Generic profile/template lookup services keyed by entity kind.

This module contains kind-dispatched canonical read services shared by profile
and template adapters. Callers provide an ``EntityKind`` (or matching string),
and the helpers resolve the correct repositories while preserving consistent
error behaviour.
"""

from __future__ import annotations

import dataclasses as dc
import typing as typ

from episodic.canonical.profile_templates.helpers import (
    _get_entity_with_latest_revision,
    _with_latest_revisions,
)
from episodic.canonical.profile_templates.types import (
    EntityKind,
    _EpisodeTemplateHistoryRepository,
    _EpisodeTemplateRepository,
    _RevisionedEntry,
    _SeriesProfileHistoryRepository,
    _SeriesProfileRepository,
    _VersionedEntity,
)

if typ.TYPE_CHECKING:
    import uuid

    from episodic.canonical.ports import CanonicalUnitOfWork


@dc.dataclass(frozen=True, slots=True)
class _KindDispatch:
    """Repository callables and labels for one entity kind."""

    human_label: str
    entity_get: typ.Callable[[uuid.UUID], typ.Awaitable[object | None]]
    fetch_latest: typ.Callable[
        [uuid.UUID],
        typ.Awaitable[_RevisionedEntry | None],
    ]
    list_history_for_parent: typ.Callable[[uuid.UUID], typ.Awaitable[list[object]]]
    list_entities: typ.Callable[
        [uuid.UUID | None],
        typ.Awaitable[typ.Sequence[object]],
    ]
    get_latest_revisions: typ.Callable[
        [typ.Collection[uuid.UUID]],
        typ.Awaitable[dict[uuid.UUID, int]],
    ]


def _get_repos_for_kind(
    uow: CanonicalUnitOfWork,
    kind: EntityKind | str,
) -> _KindDispatch:
    """Resolve repositories and bound callables for a specific entity kind."""
    match kind:
        case EntityKind.SERIES_PROFILE | "series_profile":
            profile_repo = typ.cast("_SeriesProfileRepository", uow.series_profiles)
            profile_history_repo = typ.cast(
                "_SeriesProfileHistoryRepository",
                uow.series_profile_history,
            )

            async def _list_profiles(_: uuid.UUID | None) -> typ.Sequence[object]:
                return typ.cast("typ.Sequence[object]", await profile_repo.list())

            return _KindDispatch(
                human_label="Series profile",
                entity_get=typ.cast(
                    "typ.Callable[[uuid.UUID], typ.Awaitable[object | None]]",
                    profile_repo.get,
                ),
                fetch_latest=typ.cast(
                    "typ.Callable[[uuid.UUID], typ.Awaitable[_RevisionedEntry | None]]",
                    profile_history_repo.get_latest_for_profile,
                ),
                list_history_for_parent=typ.cast(
                    "typ.Callable[[uuid.UUID], typ.Awaitable[list[object]]]",
                    profile_history_repo.list_for_profile,
                ),
                list_entities=_list_profiles,
                get_latest_revisions=profile_history_repo.get_latest_revisions_for_profiles,
            )
        case EntityKind.EPISODE_TEMPLATE | "episode_template":
            template_repo = typ.cast(
                "_EpisodeTemplateRepository", uow.episode_templates
            )
            template_history_repo = typ.cast(
                "_EpisodeTemplateHistoryRepository",
                uow.episode_template_history,
            )

            async def _list_templates(
                series_profile_id: uuid.UUID | None,
            ) -> typ.Sequence[object]:
                return typ.cast(
                    "typ.Sequence[object]",
                    await template_repo.list(series_profile_id),
                )

            return _KindDispatch(
                human_label="Episode template",
                entity_get=typ.cast(
                    "typ.Callable[[uuid.UUID], typ.Awaitable[object | None]]",
                    template_repo.get,
                ),
                fetch_latest=typ.cast(
                    "typ.Callable[[uuid.UUID], typ.Awaitable[_RevisionedEntry | None]]",
                    template_history_repo.get_latest_for_template,
                ),
                list_history_for_parent=typ.cast(
                    "typ.Callable[[uuid.UUID], typ.Awaitable[list[object]]]",
                    template_history_repo.list_for_template,
                ),
                list_entities=_list_templates,
                get_latest_revisions=template_history_repo.get_latest_revisions_for_templates,
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
    dispatch = _get_repos_for_kind(uow, kind)
    return await _get_entity_with_latest_revision(
        entity_id=entity_id,
        entity_label=dispatch.human_label,
        get_entity=typ.cast(
            "typ.Callable[[uuid.UUID], typ.Awaitable[_VersionedEntity | None]]",
            dispatch.entity_get,
        ),
        fetch_latest=dispatch.fetch_latest,
    )


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
    dispatch = _get_repos_for_kind(uow, kind)
    return await dispatch.list_history_for_parent(parent_id)


async def list_entities_with_revisions(
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
    dispatch = _get_repos_for_kind(uow, kind)
    entities = await dispatch.list_entities(series_profile_id)
    items = await _with_latest_revisions(
        typ.cast("typ.Sequence[_VersionedEntity]", entities),
        dispatch.get_latest_revisions,
    )
    return typ.cast("list[tuple[object, int]]", items)
