"""Typed profile/template services built on generic kind-dispatched helpers.

This module exposes entity-specific canonical services and stable compatibility
names for adapters. Read/list aliases are bound via ``functools.partial``, while
create/update operations keep explicit typed request/data contracts.
"""

from __future__ import annotations

import dataclasses as dc
import datetime as dt
import typing as typ
import uuid
from functools import partial

from episodic.canonical.domain import (
    EpisodeTemplate,
    EpisodeTemplateHistoryEntry,
    SeriesProfile,
    SeriesProfileHistoryEntry,
)
from episodic.canonical.profile_templates.helpers import (
    _profile_snapshot,
    _template_snapshot,
    _update_versioned_entity,
)
from episodic.canonical.profile_templates.types import (
    AuditMetadata,
    EntityNotFoundError,
    EpisodeTemplateData,
    SeriesProfileCreateData,
    UpdateEpisodeTemplateRequest,
    UpdateSeriesProfileRequest,
)

from ._generic import (
    get_entity_with_revision,
    list_entities_with_revisions,
    list_history,
)

if typ.TYPE_CHECKING:
    from episodic.canonical.ports import CanonicalUnitOfWork


get_series_profile = partial(get_entity_with_revision, kind="series_profile")
get_episode_template = partial(get_entity_with_revision, kind="episode_template")
list_series_profile_history = partial(list_history, kind="series_profile")
list_episode_template_history = partial(list_history, kind="episode_template")
list_series_profiles = partial(list_entities_with_revisions, kind="series_profile")
list_episode_templates = partial(list_entities_with_revisions, kind="episode_template")


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
            title=request.data.title,
            description=request.data.description,
            structure=request.data.structure,
            updated_at=now,
        ),
        create_snapshot=_template_snapshot,
        audit=request.audit,
    )
