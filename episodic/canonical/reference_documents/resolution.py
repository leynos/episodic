"""Reference binding resolution service.

This module implements the episode-anchored precedence algorithm for resolving
reference document bindings. See ADR-001 for the algorithm design decision.
"""

from __future__ import annotations

import dataclasses as dc
import operator
import typing as typ

if typ.TYPE_CHECKING:
    import datetime as dt
    import uuid

    from episodic.canonical.domain import (
        ReferenceBinding,
        ReferenceDocument,
        ReferenceDocumentRevision,
    )
    from episodic.canonical.ports import CanonicalUnitOfWork


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
    """Select the best binding: latest applicable episode binding or default."""
    if applicable_episode_bindings:
        # Sort by created_at descending and take the latest
        applicable_episode_bindings.sort(key=operator.itemgetter(1), reverse=True)
        return applicable_episode_bindings[0][0]

    # Fall back to default binding
    default_bindings = [b for b in doc_bindings if b.effective_from_episode_id is None]
    if default_bindings:
        return default_bindings[0]

    return None


def _collect_applicable_episode_bindings(
    doc_bindings: list[ReferenceBinding],
    episodes_by_id: dict[uuid.UUID, typ.Any],
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
    revision_map, document_map = maps
    target_episode = await uow.episodes.get(episode_id)
    if target_episode is None:
        return []

    bindings_by_document = _group_bindings_by_document(series_bindings, revision_map)

    # Collect and prefetch all episode IDs once
    episodes_by_id = {
        ep.id: ep
        for ep in await uow.episodes.list_by_ids(
            list({
                b.effective_from_episode_id
                for bindings in bindings_by_document.values()
                for b in bindings
                if b.effective_from_episode_id is not None
            })
        )
        if ep.created_at <= target_episode.created_at
    }

    resolved = []
    for doc_id, doc_bindings in bindings_by_document.items():
        if doc_id not in document_map:
            continue

        applicable = _collect_applicable_episode_bindings(doc_bindings, episodes_by_id)
        chosen = _select_best_binding_for_document(doc_bindings, applicable)
        if chosen is not None:
            binding = _create_resolved_binding(chosen, revision_map, document_map)
            if binding is not None:
                resolved.append(binding)

    return resolved


async def resolve_bindings(
    uow: CanonicalUnitOfWork,
    *,
    series_profile_id: uuid.UUID,
    template_id: uuid.UUID | None = None,
    episode_id: uuid.UUID | None = None,
) -> list[ResolvedBinding]:
    """Resolve reference bindings for a series profile context.

    When episode_id is provided, series-profile bindings are filtered by
    effective_from_episode_id precedence. When omitted, all bindings are
    returned (backward compatible).

    Algorithm:
    1. Collect all bindings for the series profile target.
    2. Group bindings by their parent reference document.
    3. For each document group, select the binding with the latest
       effective_from_episode_id that is on or before the target episode's
       created_at timestamp. If no episode-specific binding matches, fall back
       to bindings with effective_from_episode_id = None (default).

    Parameters
    ----------
    uow : CanonicalUnitOfWork
        The unit of work for database access.
    series_profile_id : uuid.UUID
        The series profile identifier.
    template_id : uuid.UUID | None, optional
        The episode template identifier. Currently ignored; template binding
        merging is deferred to a future implementation, by default None.
    episode_id : uuid.UUID | None, optional
        The episode identifier for resolution context, by default None.

    Returns
    -------
    list[ResolvedBinding]
        The resolved bindings with their revisions and documents.

    Notes
    -----
    The template_id parameter is reserved for future template-binding support
    but is not currently used in the resolution algorithm. Template binding
    merging will be implemented in a subsequent iteration.
    """
    from episodic.canonical.domain import ReferenceBindingTargetKind

    # NOTE: Template binding merging deferred to future implementation.
    # For now, only series-profile bindings are resolved.
    _ = template_id  # Mark as intentionally unused

    series_bindings = await uow.reference_bindings.list_for_target(
        target_kind=ReferenceBindingTargetKind.SERIES_PROFILE,
        target_id=series_profile_id,
    )

    if not series_bindings:
        return []

    revision_map, document_map = await _load_revision_and_document_maps(
        uow, series_bindings
    )

    if episode_id is None:
        return _resolve_without_episode_context(
            series_bindings, revision_map, document_map
        )

    return await _resolve_with_episode_context(
        uow, series_bindings, (revision_map, document_map), episode_id=episode_id
    )
