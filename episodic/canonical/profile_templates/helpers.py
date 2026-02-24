"""Internal helper utilities for profile/template services."""

from __future__ import annotations

import datetime as dt
import typing as typ
import uuid

from sqlalchemy.exc import IntegrityError

from .types import (
    AuditMetadata,
    EntityNotFoundError,
    RevisionConflictError,
    _EntityRepository,
    _HistoryRepository,
    _RevisionedEntry,
    _VersionedEntity,
)

if typ.TYPE_CHECKING:
    from episodic.canonical.domain import EpisodeTemplate, JsonMapping, SeriesProfile
    from episodic.canonical.ports import CanonicalUnitOfWork


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
    """Return True when an integrity error indicates a revision collision."""
    # Constraint-name markers below are coupled to history uniqueness
    # constraints in ``episodic/canonical/storage/models.py``.
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


async def _update_versioned_entity[EntityT: _VersionedEntity, HistoryT](  # noqa: PLR0913  # TODO(@episodic-dev): https://github.com/leynos/episodic/issues/1234 dependency-injected collaborators keep this explicit
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
