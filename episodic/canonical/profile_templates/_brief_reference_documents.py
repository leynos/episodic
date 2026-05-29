"""Reference-document resolution strategies for structured-brief assembly."""

import typing as typ

from episodic.canonical.domain import ReferenceBindingTargetKind

from .types import EntityNotFoundError

if typ.TYPE_CHECKING:
    import uuid

    from episodic.canonical.domain import (
        EpisodeTemplate,
        JsonMapping,
        ReferenceBinding,
    )
    from episodic.canonical.unit_of_work_protocols import CanonicalUnitOfWork


async def _validate_episode_for_brief(
    uow: CanonicalUnitOfWork,
    *,
    episode_id: uuid.UUID,
    profile_id: uuid.UUID,
) -> None:
    """Verify that the episode exists and belongs to the series profile."""
    episode = await uow.episodes.get(episode_id)
    if episode is None or episode.series_profile_id != profile_id:
        msg = (
            f"Episode {episode_id} not found or does not belong to "
            f"series profile {profile_id}."
        )
        raise EntityNotFoundError(msg, entity_id=str(episode_id))


async def _load_episode_aware_reference_documents(
    uow: CanonicalUnitOfWork,
    *,
    profile_id: uuid.UUID,
    template_items: list[tuple[EpisodeTemplate, int]],
    episode_id: uuid.UUID,
) -> list[JsonMapping]:
    """Load reference documents using episode-aware resolution.

    Validates the episode, resolves series-level bindings via
    ``effective_from_episode_id`` precedence, then appends any template-scoped
    bindings without episode filtering.
    """
    from episodic.canonical.reference_documents import resolve_bindings

    from ._brief_loaders import (
        _load_documents_by_id,
        _load_revisions_by_id,
        _serialize_bindings_for_owner,
    )
    from ._brief_serializers import _serialize_reference_document_for_brief

    await _validate_episode_for_brief(uow, episode_id=episode_id, profile_id=profile_id)
    resolved_bindings = await resolve_bindings(
        uow,
        series_profile_id=profile_id,
        episode_id=episode_id,
    )
    resolved_documents: list[JsonMapping] = []
    for resolved in resolved_bindings:
        if resolved.document.owner_series_profile_id != profile_id:
            msg = (
                f"Reference document {resolved.document.id} does not belong to "
                f"requested series profile {profile_id}."
            )
            raise ValueError(msg)
        resolved_documents.append(
            _serialize_reference_document_for_brief(
                binding=resolved.binding,
                document=resolved.document,
                revision=resolved.revision,
            )
        )

    template_documents: list[JsonMapping] = []
    all_template_bindings: list[ReferenceBinding] = []
    for template, _ in template_items:
        bindings = await uow.reference_bindings.list_for_target(
            target_kind=ReferenceBindingTargetKind.EPISODE_TEMPLATE,
            target_id=template.id,
        )
        all_template_bindings.extend(bindings)

    if all_template_bindings:
        revisions_by_id = await _load_revisions_by_id(
            uow=uow,
            bindings=all_template_bindings,
        )
        documents_by_id = await _load_documents_by_id(
            uow=uow,
            revisions=revisions_by_id.values(),
        )
        template_documents = _serialize_bindings_for_owner(
            bindings=all_template_bindings,
            revisions_by_id=revisions_by_id,
            documents_by_id=documents_by_id,
            owner_series_profile_id=profile_id,
        )
    return resolved_documents + template_documents


async def _load_legacy_reference_documents(
    uow: CanonicalUnitOfWork,
    *,
    profile_id: uuid.UUID,
    template_items: list[tuple[EpisodeTemplate, int]],
) -> list[JsonMapping]:
    """Load reference documents using the legacy (non-episode-aware) path.

    Aggregates all SERIES_PROFILE bindings plus EPISODE_TEMPLATE bindings for
    every template in ``template_items``, then serialises the full set.
    """
    from ._brief_loaders import (
        _load_documents_by_id,
        _load_revisions_by_id,
        _serialize_bindings_for_owner,
    )

    all_bindings = await uow.reference_bindings.list_for_target(
        target_kind=ReferenceBindingTargetKind.SERIES_PROFILE,
        target_id=profile_id,
    )

    for template, _ in template_items:
        all_bindings.extend(
            await uow.reference_bindings.list_for_target(
                target_kind=ReferenceBindingTargetKind.EPISODE_TEMPLATE,
                target_id=template.id,
            )
        )

    if not all_bindings:
        return []

    revisions_by_id = await _load_revisions_by_id(
        uow=uow,
        bindings=all_bindings,
    )
    documents_by_id = await _load_documents_by_id(
        uow=uow,
        revisions=revisions_by_id.values(),
    )
    return _serialize_bindings_for_owner(
        bindings=all_bindings,
        revisions_by_id=revisions_by_id,
        documents_by_id=documents_by_id,
        owner_series_profile_id=profile_id,
    )


async def _load_reference_documents_for_brief(
    uow: CanonicalUnitOfWork,
    *,
    profile_id: uuid.UUID,
    template_items: list[tuple[EpisodeTemplate, int]],
    episode_id: uuid.UUID | None,
) -> list[JsonMapping]:
    """Load serialized reference documents for profile/template contexts."""
    if episode_id is not None:
        return await _load_episode_aware_reference_documents(
            uow,
            profile_id=profile_id,
            template_items=template_items,
            episode_id=episode_id,
        )
    return await _load_legacy_reference_documents(
        uow,
        profile_id=profile_id,
        template_items=template_items,
    )
