"""Generic profile/template lookup services keyed by entity kind.

This module contains kind-dispatched canonical read services shared by profile
and template adapters. Callers provide an ``EntityKind`` (or matching string),
and the helpers resolve the correct repositories while preserving consistent
error behaviour.
"""

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
    import collections.abc as cabc
    import uuid

    from episodic.canonical.pagination import Pagination
    from episodic.canonical.unit_of_work_protocols import CanonicalUnitOfWork

    type _RevisionFetcher = cabc.Callable[
        [uuid.UUID],
        cabc.Awaitable[_RevisionedEntry | None],
    ]


@dc.dataclass(frozen=True, slots=True)
class _KindDispatch:
    """Repository callables and labels for one entity kind."""

    human_label: str
    entity_get: cabc.Callable[[uuid.UUID], cabc.Awaitable[object | None]]
    fetch_latest: cabc.Callable[
        [uuid.UUID],
        cabc.Awaitable[_RevisionedEntry | None],
    ]
    list_history_for_parent: cabc.Callable[[uuid.UUID], cabc.Awaitable[list[object]]]
    list_history_for_parent_paged: cabc.Callable[
        [uuid.UUID, int, int],
        cabc.Awaitable[list[object]],
    ]
    count_history_for_parent: cabc.Callable[[uuid.UUID], cabc.Awaitable[int]]
    list_entities: cabc.Callable[
        [uuid.UUID | None, int | None, int],
        cabc.Awaitable[cabc.Sequence[object]],
    ]
    count_entities: cabc.Callable[[uuid.UUID | None], cabc.Awaitable[int]]
    get_latest_revisions: cabc.Callable[
        [cabc.Collection[uuid.UUID]],
        cabc.Awaitable[dict[uuid.UUID, int]],
    ]


def _get_repos_for_kind(  # noqa: C901  # Inlining mandated by design; arm-extraction was previously flagged as duplication.
    uow: CanonicalUnitOfWork,
    kind: EntityKind | str,
) -> _KindDispatch:
    """Resolve repositories and bound callables for a specific entity kind."""
    # Each match arm uses arm-local repo names (e.g. `profile_history_repo`,
    # `template_history_repo`) rather than a shared `history_repo`. Python's
    # `match` does not introduce a fresh scope per arm, so a shared name would
    # be unioned by static analysis and the per-arm closures could not resolve
    # their kind-specific methods (`list_for_profile_paged` vs
    # `list_for_template_paged`). The closure names (`_list_entities`,
    # `_count_entities`, `_list_history_paged`) are intentionally identical
    # across arms; only one arm runs at runtime.
    match kind:
        case EntityKind.SERIES_PROFILE | "series_profile":
            profile_repo = typ.cast("_SeriesProfileRepository", uow.series_profiles)
            profile_history_repo = typ.cast(
                "_SeriesProfileHistoryRepository",
                uow.series_profile_history,
            )

            async def _list_entities(
                _: uuid.UUID | None,
                limit: int | None,
                offset: int,
            ) -> cabc.Sequence[object]:
                return typ.cast(
                    "cabc.Sequence[object]",
                    await profile_repo.list(limit=limit, offset=offset),
                )

            async def _count_entities(_: uuid.UUID | None) -> int:
                return await profile_repo.count()

            async def _list_history_paged(
                parent_id: uuid.UUID,
                limit: int,
                offset: int,
            ) -> list[object]:
                return typ.cast(
                    "list[object]",
                    await profile_history_repo.list_for_profile_paged(
                        parent_id,
                        limit=limit,
                        offset=offset,
                    ),
                )

            return _KindDispatch(
                human_label="Series profile",
                entity_get=typ.cast(
                    "cabc.Callable[[uuid.UUID], cabc.Awaitable[object | None]]",
                    profile_repo.get,
                ),
                fetch_latest=typ.cast(
                    "_RevisionFetcher",
                    profile_history_repo.get_latest_for_profile,
                ),
                list_history_for_parent=typ.cast(
                    "cabc.Callable[[uuid.UUID], cabc.Awaitable[list[object]]]",
                    profile_history_repo.list_for_profile,
                ),
                list_history_for_parent_paged=_list_history_paged,
                count_history_for_parent=profile_history_repo.count_for_profile,
                list_entities=_list_entities,
                count_entities=_count_entities,
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

            async def _list_entities(
                series_profile_id: uuid.UUID | None,
                limit: int | None,
                offset: int,
            ) -> cabc.Sequence[object]:
                return typ.cast(
                    "cabc.Sequence[object]",
                    await template_repo.list(
                        series_profile_id,
                        limit=limit,
                        offset=offset,
                    ),
                )

            async def _count_entities(series_profile_id: uuid.UUID | None) -> int:
                return await template_repo.count(series_profile_id)

            async def _list_history_paged(
                parent_id: uuid.UUID,
                limit: int,
                offset: int,
            ) -> list[object]:
                return typ.cast(
                    "list[object]",
                    await template_history_repo.list_for_template_paged(
                        parent_id,
                        limit=limit,
                        offset=offset,
                    ),
                )

            return _KindDispatch(
                human_label="Episode template",
                entity_get=typ.cast(
                    "cabc.Callable[[uuid.UUID], cabc.Awaitable[object | None]]",
                    template_repo.get,
                ),
                fetch_latest=typ.cast(
                    "_RevisionFetcher",
                    template_history_repo.get_latest_for_template,
                ),
                list_history_for_parent=typ.cast(
                    "cabc.Callable[[uuid.UUID], cabc.Awaitable[list[object]]]",
                    template_history_repo.list_for_template,
                ),
                list_history_for_parent_paged=_list_history_paged,
                count_history_for_parent=template_history_repo.count_for_template,
                list_entities=_list_entities,
                count_entities=_count_entities,
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
            "cabc.Callable[[uuid.UUID], cabc.Awaitable[_VersionedEntity | None]]",
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


async def list_history_paged(
    uow: CanonicalUnitOfWork,
    *,
    parent_id: uuid.UUID,
    kind: EntityKind | str,
    page: Pagination,
) -> tuple[list[object], int]:
    """List paged history entries and the total for one parent entity."""
    dispatch = _get_repos_for_kind(uow, kind)
    items = await dispatch.list_history_for_parent_paged(
        parent_id, page.limit, page.offset
    )
    total = await dispatch.count_history_for_parent(parent_id)
    return items, total


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
    entities = await dispatch.list_entities(series_profile_id, None, 0)
    items = await _with_latest_revisions(
        typ.cast("cabc.Sequence[_VersionedEntity]", entities),
        dispatch.get_latest_revisions,
    )
    return typ.cast("list[tuple[object, int]]", items)


async def list_entities_with_revisions_paged(
    uow: CanonicalUnitOfWork,
    *,
    kind: EntityKind | str,
    page: Pagination,
    series_profile_id: uuid.UUID | None = None,
) -> tuple[list[tuple[object, int]], int]:
    """List entities with latest revisions and their unpaginated total."""
    dispatch = _get_repos_for_kind(uow, kind)
    entities = await dispatch.list_entities(series_profile_id, page.limit, page.offset)
    items = await _with_latest_revisions(
        typ.cast("cabc.Sequence[_VersionedEntity]", entities),
        dispatch.get_latest_revisions,
    )
    total = await dispatch.count_entities(series_profile_id)
    return typ.cast("list[tuple[object, int]]", items), total
