"""Application services for series profiles and episode templates."""

from __future__ import annotations

import dataclasses as dc
import datetime as dt
import typing as typ
import uuid
from itertools import starmap

from .domain import (
    EpisodeTemplate,
    EpisodeTemplateHistoryEntry,
    SeriesProfile,
    SeriesProfileHistoryEntry,
)

if typ.TYPE_CHECKING:
    from .ports import CanonicalUnitOfWork

type JsonMapping = dict[str, typ.Any]


@dc.dataclass(frozen=True, slots=True)
class AuditMetadata:
    """Audit metadata for versioned operations."""

    actor: str | None
    note: str | None


@dc.dataclass(frozen=True, slots=True)
class SeriesProfileData:
    """Entity data for series profile operations."""

    title: str
    description: str | None
    configuration: JsonMapping


@dc.dataclass(frozen=True, slots=True)
class SeriesProfileCreateData(SeriesProfileData):
    """Entity data for creating a series profile."""

    slug: str


@dc.dataclass(frozen=True, slots=True)
class SeriesProfileUpdateFields(SeriesProfileData):
    """Entity data for updating a series profile."""


@dc.dataclass(frozen=True, slots=True)
class EpisodeTemplateUpdateFields:
    """Entity data for updating an episode template."""

    title: str
    description: str | None
    structure: JsonMapping


@dc.dataclass(frozen=True, slots=True)
class EpisodeTemplateData:
    """Data for creating or updating an episode template."""

    slug: str
    title: str
    description: str | None
    structure: JsonMapping
    actor: str | None
    note: str | None


class EntityNotFoundError(LookupError):
    """Raised when an expected profile or template does not exist."""


class RevisionConflictError(ValueError):
    """Raised when optimistic-lock revision preconditions are not met."""


class _RevisionedEntry(typ.Protocol):
    """Protocol for history entries that expose a revision."""

    revision: int


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


async def get_series_profile(
    uow: CanonicalUnitOfWork,
    *,
    profile_id: uuid.UUID,
) -> tuple[SeriesProfile, int]:
    """Fetch a series profile and latest revision."""
    profile = await uow.series_profiles.get(profile_id)
    if profile is None:
        msg = f"Series profile {profile_id} not found."
        raise EntityNotFoundError(msg)
    revision = await _get_latest_revision(
        uow.series_profile_history.get_latest_for_profile,
        profile_id,
    )
    return profile, revision


async def list_series_profiles(
    uow: CanonicalUnitOfWork,
) -> list[tuple[SeriesProfile, int]]:
    """List all series profiles with current revision values."""
    profiles = await uow.series_profiles.list()
    items: list[tuple[SeriesProfile, int]] = []
    for profile in profiles:
        revision = await _get_latest_revision(
            uow.series_profile_history.get_latest_for_profile,
            profile.id,
        )
        items.append((profile, revision))
    return items


async def update_series_profile(  # noqa: PLR0913
    uow: CanonicalUnitOfWork,
    *,
    profile_id: uuid.UUID,
    expected_revision: int,
    data: SeriesProfileData,
    audit: AuditMetadata,
) -> tuple[SeriesProfile, int]:
    """Update a series profile with optimistic-lock revision checks."""
    profile = await uow.series_profiles.get(profile_id)
    if profile is None:
        msg = f"Series profile {profile_id} not found."
        raise EntityNotFoundError(msg)
    latest_revision = await _get_latest_revision(
        uow.series_profile_history.get_latest_for_profile,
        profile_id,
    )
    _check_revision_conflict(
        expected_revision=expected_revision,
        latest_revision=latest_revision,
        entity_label="Series profile",
    )

    now = dt.datetime.now(dt.UTC)
    updated_profile = dc.replace(
        profile,
        title=data.title,
        description=data.description,
        configuration=data.configuration,
        updated_at=now,
    )
    next_revision = latest_revision + 1
    history_entry = SeriesProfileHistoryEntry(
        id=uuid.uuid4(),
        series_profile_id=updated_profile.id,
        revision=next_revision,
        actor=audit.actor,
        note=audit.note,
        snapshot=_profile_snapshot(updated_profile),
        created_at=now,
    )
    await uow.series_profiles.update(updated_profile)
    await uow.series_profile_history.add(history_entry)
    await uow.commit()
    return updated_profile, next_revision


async def list_series_profile_history(
    uow: CanonicalUnitOfWork,
    *,
    profile_id: uuid.UUID,
) -> list[SeriesProfileHistoryEntry]:
    """List immutable history entries for a series profile."""
    return await uow.series_profile_history.list_for_profile(profile_id)


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


async def get_episode_template(
    uow: CanonicalUnitOfWork,
    *,
    template_id: uuid.UUID,
) -> tuple[EpisodeTemplate, int]:
    """Fetch an episode template and latest revision."""
    template = await uow.episode_templates.get(template_id)
    if template is None:
        msg = f"Episode template {template_id} not found."
        raise EntityNotFoundError(msg)
    revision = await _get_latest_revision(
        uow.episode_template_history.get_latest_for_template,
        template_id,
    )
    return template, revision


async def list_episode_templates(
    uow: CanonicalUnitOfWork,
    *,
    series_profile_id: uuid.UUID | None,
) -> list[tuple[EpisodeTemplate, int]]:
    """List episode templates with current revision values."""
    templates = await uow.episode_templates.list(series_profile_id)
    items: list[tuple[EpisodeTemplate, int]] = []
    for template in templates:
        revision = await _get_latest_revision(
            uow.episode_template_history.get_latest_for_template,
            template.id,
        )
        items.append((template, revision))
    return items


async def update_episode_template(  # noqa: PLR0913
    uow: CanonicalUnitOfWork,
    *,
    template_id: uuid.UUID,
    expected_revision: int,
    fields: EpisodeTemplateUpdateFields,
    audit: AuditMetadata,
) -> tuple[EpisodeTemplate, int]:
    """Update an episode template with optimistic-lock revision checks."""
    template = await uow.episode_templates.get(template_id)
    if template is None:
        msg = f"Episode template {template_id} not found."
        raise EntityNotFoundError(msg)
    latest_revision = await _get_latest_revision(
        uow.episode_template_history.get_latest_for_template,
        template_id,
    )
    _check_revision_conflict(
        expected_revision=expected_revision,
        latest_revision=latest_revision,
        entity_label="Episode template",
    )

    now = dt.datetime.now(dt.UTC)
    updated_template = dc.replace(
        template,
        title=fields.title,
        description=fields.description,
        structure=fields.structure,
        updated_at=now,
    )
    next_revision = latest_revision + 1
    history_entry = EpisodeTemplateHistoryEntry(
        id=uuid.uuid4(),
        episode_template_id=updated_template.id,
        revision=next_revision,
        actor=audit.actor,
        note=audit.note,
        snapshot=_template_snapshot(updated_template),
        created_at=now,
    )
    await uow.episode_templates.update(updated_template)
    await uow.episode_template_history.add(history_entry)
    await uow.commit()
    return updated_template, next_revision


async def list_episode_template_history(
    uow: CanonicalUnitOfWork,
    *,
    template_id: uuid.UUID,
) -> list[EpisodeTemplateHistoryEntry]:
    """List immutable history entries for an episode template."""
    return await uow.episode_template_history.list_for_template(template_id)


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


async def build_series_brief(
    uow: CanonicalUnitOfWork,
    *,
    profile_id: uuid.UUID,
    template_id: uuid.UUID | None,
) -> JsonMapping:
    """Build a structured brief payload for downstream generators."""
    profile, profile_revision = await get_series_profile(uow, profile_id=profile_id)
    if template_id is None:
        template_items = await list_episode_templates(uow, series_profile_id=profile.id)
    else:
        template, template_revision = await get_episode_template(
            uow,
            template_id=template_id,
        )
        if template.series_profile_id != profile.id:
            msg = (
                f"Episode template {template.id} does not belong to "
                f"series profile {profile.id}."
            )
            raise EntityNotFoundError(msg)
        template_items = [(template, template_revision)]

    return {
        "series_profile": _serialize_profile_for_brief(profile, profile_revision),
        "episode_templates": list(
            starmap(_serialize_template_for_brief, template_items)
        ),
    }
