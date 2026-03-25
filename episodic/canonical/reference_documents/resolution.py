"""Reference binding resolution service.

This module implements the episode-anchored precedence algorithm for resolving
reference document bindings. See ADR-001 for the algorithm design decision.
"""

import dataclasses as dc
import operator
import typing as typ

if typ.TYPE_CHECKING:
    import datetime as dt
    import uuid

    from episodic.canonical.domain import (
        CanonicalEpisode,
        ReferenceBinding,
        ReferenceDocument,
        ReferenceDocumentRevision,
    )
    from episodic.canonical.ports import CanonicalUnitOfWork

from episodic.canonical.domain import ReferenceBindingTargetKind


@dc.dataclass(frozen=True, slots=True)
class ResolvedBinding:
    """A resolved binding triple: binding, revision, and document."""

    binding: ReferenceBinding
    revision: ReferenceDocumentRevision
    document: ReferenceDocument


async def _load_revision_and_document_maps(
    uow: CanonicalUnitOfWork,
    series_bindings: list[ReferenceBinding],
) -> tuple[
    dict[uuid.UUID, ReferenceDocumentRevision], dict[uuid.UUID, ReferenceDocument]
]:
    """Load revisions and documents for bindings, returning lookup maps."""
    revision_ids = {b.reference_document_revision_id for b in series_bindings}
    revisions = await uow.reference_document_revisions.list_by_ids(list(revision_ids))
    revision_map = {r.id: r for r in revisions}

    document_ids = {r.reference_document_id for r in revisions}
    documents = await uow.reference_documents.list_by_ids(list(document_ids))
    document_map = {d.id: d for d in documents}

    return revision_map, document_map


def _create_resolved_binding(
    binding: ReferenceBinding,
    revision_map: dict[uuid.UUID, ReferenceDocumentRevision],
    document_map: dict[uuid.UUID, ReferenceDocument],
) -> ResolvedBinding | None:
    """Create a ResolvedBinding if revision and document exist, else None."""
    revision = revision_map.get(binding.reference_document_revision_id)
    if revision is None:
        return None
    document = document_map.get(revision.reference_document_id)
    if document is None:
        return None
    return ResolvedBinding(binding=binding, revision=revision, document=document)


def _resolve_without_episode_context(
    series_bindings: list[ReferenceBinding],
    revision_map: dict[uuid.UUID, ReferenceDocumentRevision],
    document_map: dict[uuid.UUID, ReferenceDocument],
) -> list[ResolvedBinding]:
    """Resolve all bindings without episode precedence filtering."""
    resolved = []
    for binding in series_bindings:
        resolved_binding = _create_resolved_binding(binding, revision_map, document_map)
        if resolved_binding is not None:
            resolved.append(resolved_binding)
    return resolved


def _group_bindings_by_document(
    series_bindings: list[ReferenceBinding],
    revision_map: dict[uuid.UUID, ReferenceDocumentRevision],
) -> dict[uuid.UUID, list[ReferenceBinding]]:
    """Group bindings by their reference document ID."""
    bindings_by_document: dict[uuid.UUID, list[ReferenceBinding]] = {}
    for binding in series_bindings:
        revision = revision_map.get(binding.reference_document_revision_id)
        if revision is None:
            continue
        doc_id = revision.reference_document_id
        bindings_by_document.setdefault(doc_id, []).append(binding)
    return bindings_by_document


def _select_best_binding_for_document(
    doc_bindings: list[ReferenceBinding],
    applicable_episode_bindings: list[tuple[ReferenceBinding, dt.datetime]],
) -> ReferenceBinding | None:
    """Select the best binding: latest applicable episode binding or default.

    Selection is deterministic: for applicable episode bindings, ties on episode
    timestamp are broken by binding.created_at; for default bindings, the latest
    by created_at is chosen.
    """
    if applicable_episode_bindings:
        # Select max by episode timestamp, then by binding created_at for ties
        return max(
            applicable_episode_bindings,
            key=lambda item: (item[1], item[0].created_at),
        )[0]

    # Fall back to default binding (latest by created_at)
    default_bindings = [b for b in doc_bindings if b.effective_from_episode_id is None]
    if default_bindings:
        return max(default_bindings, key=operator.attrgetter("created_at"))

    return None


def _collect_applicable_episode_bindings(
    doc_bindings: list[ReferenceBinding],
    episodes_by_id: dict[uuid.UUID, CanonicalEpisode],
) -> list[tuple[ReferenceBinding, dt.datetime]]:
    """Collect episode bindings that are applicable for this document."""
    applicable = []
    for binding in doc_bindings:
        eid = binding.effective_from_episode_id
        if eid is None:
            continue
        episode = episodes_by_id.get(eid)
        if episode is not None:
            applicable.append((binding, episode.created_at))
    return applicable


async def _build_applicable_episodes_map(
    uow: CanonicalUnitOfWork,
    bindings_by_document: dict[uuid.UUID, list[ReferenceBinding]],
    target_created_at: dt.datetime,
) -> dict[uuid.UUID, CanonicalEpisode]:
    """Fetch episodes whose created_at is on or before the target timestamp.

    Returns a mapping of episode id → episode for use in per-document
    binding selection.
    """
    episode_ids = {
        b.effective_from_episode_id
        for bindings in bindings_by_document.values()
        for b in bindings
        if b.effective_from_episode_id is not None
    }
    episodes = await uow.episodes.list_by_ids(list(episode_ids))
    return {ep.id: ep for ep in episodes if ep.created_at <= target_created_at}


def _resolve_single_document(
    doc_id: uuid.UUID,
    doc_bindings: list[ReferenceBinding],
    episodes_by_id: dict[uuid.UUID, CanonicalEpisode],
    maps: tuple[
        dict[uuid.UUID, ReferenceDocumentRevision],
        dict[uuid.UUID, ReferenceDocument],
    ],
) -> ResolvedBinding | None:
    """Resolve the best binding for a single document with episode context.

    Returns the resolved binding if one exists, else None.
    """
    revision_map, document_map = maps
    if doc_id not in document_map:
        return None
    applicable = _collect_applicable_episode_bindings(doc_bindings, episodes_by_id)
    chosen = _select_best_binding_for_document(doc_bindings, applicable)
    if chosen is None:
        return None
    return _create_resolved_binding(chosen, revision_map, document_map)


async def _resolve_with_episode_context(
    uow: CanonicalUnitOfWork,
    series_bindings: list[ReferenceBinding],
    maps: tuple[
        dict[uuid.UUID, ReferenceDocumentRevision], dict[uuid.UUID, ReferenceDocument]
    ],
    *,
    episode_id: uuid.UUID,
) -> list[ResolvedBinding]:
    """Resolve bindings with episode-aware precedence logic."""
    revision_map, _ = maps
    target_episode = await uow.episodes.get(episode_id)
    if target_episode is None:
        return []

    bindings_by_document = _group_bindings_by_document(series_bindings, revision_map)
    episodes_by_id = await _build_applicable_episodes_map(
        uow, bindings_by_document, target_episode.created_at
    )

    resolved = []
    for doc_id, doc_bindings in bindings_by_document.items():
        result = _resolve_single_document(doc_id, doc_bindings, episodes_by_id, maps)
        if result is not None:
            resolved.append(result)
    return resolved


async def _load_template_bindings(
    uow: CanonicalUnitOfWork,
    template_id: uuid.UUID,
) -> list[ReferenceBinding]:
    """Load all bindings for the given episode template target."""
    return await uow.reference_bindings.list_for_target(
        target_kind=ReferenceBindingTargetKind.EPISODE_TEMPLATE,
        target_id=template_id,
    )


async def resolve_bindings(
    uow: CanonicalUnitOfWork,
    *,
    series_profile_id: uuid.UUID,
    template_id: uuid.UUID | None = None,
    episode_id: uuid.UUID | None = None,
) -> list[ResolvedBinding]:
    """Resolve reference bindings for a series profile context.

    When episode_id is provided, series-profile bindings are filtered by
    effective_from_episode_id precedence. Template bindings are always included
    without episode filtering (domain invariant: template bindings have no
    effective_from_episode_id). When episode_id is omitted, all bindings are
    returned (backward compatible).

    Algorithm:
    1. Collect all bindings for the series profile target.
    2. If template_id is provided, collect all bindings for that template.
    3. Group bindings by their parent reference document.
    4. For each document group, select the binding with the latest
       effective_from_episode_id that is on or before the target episode's
       created_at timestamp. If no episode-specific binding matches, fall back
       to bindings with effective_from_episode_id = None (default). Template
       bindings are merged into results without episode filtering.

    Parameters
    ----------
    uow : CanonicalUnitOfWork
        The unit of work for database access.
    series_profile_id : uuid.UUID
        The series profile identifier.
    template_id : uuid.UUID | None, optional
        The episode template identifier for merging template bindings,
        by default None.
    episode_id : uuid.UUID | None, optional
        The episode identifier for resolution context, by default None.

    Returns
    -------
    list[ResolvedBinding]
        The resolved bindings with their revisions and documents.

    """
    series_bindings = await uow.reference_bindings.list_for_target(
        target_kind=ReferenceBindingTargetKind.SERIES_PROFILE,
        target_id=series_profile_id,
    )

    template_bindings: list[ReferenceBinding] = []
    if template_id is not None:
        template_bindings = await _load_template_bindings(uow, template_id)

    all_bindings = series_bindings + template_bindings
    if not all_bindings:
        return []

    revision_map, document_map = await _load_revision_and_document_maps(
        uow, all_bindings
    )

    if episode_id is None:
        return _resolve_without_episode_context(
            all_bindings, revision_map, document_map
        )

    # Template bindings are always included without episode filtering
    template_resolved = _resolve_without_episode_context(
        template_bindings, revision_map, document_map
    )
    series_resolved = await _resolve_with_episode_context(
        uow, series_bindings, (revision_map, document_map), episode_id=episode_id
    )
    return series_resolved + template_resolved
