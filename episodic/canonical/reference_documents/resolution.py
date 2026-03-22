"""Reference binding resolution service.

This module implements the episode-anchored precedence algorithm for resolving
reference document bindings. See ADR-001 for the algorithm design decision.
"""

import dataclasses as dc
import operator
import typing as typ

if typ.TYPE_CHECKING:
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


async def resolve_bindings(  # noqa: C901, PLR0912, PLR0915, PLR0914
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
    4. If template_id is provided, collect template bindings and merge.

    Parameters
    ----------
    uow : CanonicalUnitOfWork
        The unit of work for database access.
    series_profile_id : uuid.UUID
        The series profile identifier.
    template_id : uuid.UUID | None, optional
        The episode template identifier, by default None.
    episode_id : uuid.UUID | None, optional
        The episode identifier for resolution context, by default None.

    Returns
    -------
    list[ResolvedBinding]
        The resolved bindings with their revisions and documents.
    """
    # Collect series profile bindings
    from episodic.canonical.domain import ReferenceBindingTargetKind

    series_bindings = await uow.reference_bindings.list_for_target(
        target_kind=ReferenceBindingTargetKind.SERIES_PROFILE,
        target_id=series_profile_id,
    )

    if not series_bindings:
        return []

    # Load all revisions and documents for the bindings
    revision_ids = {b.reference_document_revision_id for b in series_bindings}
    revisions = await uow.reference_document_revisions.list_by_ids(list(revision_ids))
    revision_map = {r.id: r for r in revisions}

    document_ids = {r.reference_document_id for r in revisions}
    documents = await uow.reference_documents.list_by_ids(list(document_ids))
    document_map = {d.id: d for d in documents}

    # If no episode context, return all bindings (backward compatible)
    if episode_id is None:
        resolved = []
        for binding in series_bindings:
            revision = revision_map.get(binding.reference_document_revision_id)
            if revision is None:
                continue
            document = document_map.get(revision.reference_document_id)
            if document is None:
                continue
            resolved.append(
                ResolvedBinding(
                    binding=binding,
                    revision=revision,
                    document=document,
                )
            )
        return resolved

    # Episode-aware resolution: group bindings by document and apply precedence
    target_episode = await uow.episodes.get(episode_id)
    if target_episode is None:
        # Episode not found; return empty
        return []

    target_created_at = target_episode.created_at

    # Group bindings by document
    bindings_by_document: dict[uuid.UUID, list[ReferenceBinding]] = {}
    for binding in series_bindings:
        revision = revision_map.get(binding.reference_document_revision_id)
        if revision is None:
            continue
        doc_id = revision.reference_document_id
        bindings_by_document.setdefault(doc_id, []).append(binding)

    # Resolve one binding per document
    resolved = []
    for doc_id, doc_bindings in bindings_by_document.items():
        document = document_map.get(doc_id)
        if document is None:
            continue

        # Separate default bindings (None effective_from_episode_id) from
        # episode-specific
        default_bindings = [
            b for b in doc_bindings if b.effective_from_episode_id is None
        ]
        episode_bindings = [
            b for b in doc_bindings if b.effective_from_episode_id is not None
        ]

        # Fetch episode created_at timestamps for episode-specific bindings
        if episode_bindings:
            episode_ids = {
                b.effective_from_episode_id
                for b in episode_bindings
                if b.effective_from_episode_id is not None
            }
            episodes = {
                ep.id: ep
                for ep in await uow.episodes.list_by_ids(list(episode_ids))
                if ep.created_at <= target_created_at
            }

            # Find the binding with the latest effective_from_episode_id <= target
            applicable_bindings = []
            for binding in episode_bindings:
                if binding.effective_from_episode_id is None:
                    continue
                effective_episode = episodes.get(binding.effective_from_episode_id)
                if effective_episode is not None:
                    applicable_bindings.append((binding, effective_episode.created_at))

            if applicable_bindings:
                # Sort by created_at descending and take the latest
                applicable_bindings.sort(key=operator.itemgetter(1), reverse=True)
                chosen_binding = applicable_bindings[0][0]
                revision = revision_map[chosen_binding.reference_document_revision_id]
                resolved.append(
                    ResolvedBinding(
                        binding=chosen_binding,
                        revision=revision,
                        document=document,
                    )
                )
                continue

        # No applicable episode-specific binding; fall back to default
        if default_bindings:
            # If multiple defaults exist, pick the first (should be unique per
            # target+doc)
            chosen_binding = default_bindings[0]
            revision = revision_map[chosen_binding.reference_document_revision_id]
            resolved.append(
                ResolvedBinding(
                    binding=chosen_binding,
                    revision=revision,
                    document=document,
                )
            )

    return resolved
