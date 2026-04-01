"""Reference binding resolution service.

This module implements the episode-anchored precedence algorithm for resolving
reference document bindings. See ADR-001 for the algorithm design decision.
"""

import dataclasses as dc
import datetime as dt
import typing as typ
import uuid

if typ.TYPE_CHECKING:
    from episodic.canonical.domain import (
        CanonicalEpisode,
        ReferenceBinding,
        ReferenceDocument,
        ReferenceDocumentRevision,
    )
    from episodic.canonical.ports import CanonicalUnitOfWork

from episodic.canonical.domain import ReferenceBindingTargetKind, SourceDocument


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
    timestamp are broken by binding.created_at, then by binding.id; for default
    bindings, the latest by created_at is chosen, with binding.id as tiebreaker.
    """
    if applicable_episode_bindings:
        # Select max by episode timestamp, then by binding created_at, then by id
        return max(
            applicable_episode_bindings,
            key=lambda item: (item[1], item[0].created_at, item[0].id),
        )[0]

    # Fall back to default binding (latest by created_at, then by id)
    default_bindings = [b for b in doc_bindings if b.effective_from_episode_id is None]
    if default_bindings:
        return max(default_bindings, key=lambda b: (b.created_at, b.id))

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
    target_episode_created_at: dt.datetime,
) -> list[ResolvedBinding]:
    """Resolve bindings with episode-aware precedence logic."""
    revision_map, _ = maps

    bindings_by_document = _group_bindings_by_document(series_bindings, revision_map)
    episodes_by_id = await _build_applicable_episodes_map(
        uow, bindings_by_document, target_episode_created_at
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


async def _episode_belongs_to_series(
    uow: CanonicalUnitOfWork,
    episode_id: uuid.UUID,
    series_profile_id: uuid.UUID,
) -> CanonicalEpisode | None:
    """Return the episode if it exists and belongs to the series profile, else None."""
    episode = await uow.episodes.get(episode_id)
    if episode is not None and episode.series_profile_id == series_profile_id:
        return episode
    return None


async def _template_belongs_to_series(
    uow: CanonicalUnitOfWork,
    template_id: uuid.UUID,
    series_profile_id: uuid.UUID,
) -> bool:
    """Return True if the template exists and belongs to the given series profile."""
    template = await uow.episode_templates.get(template_id)
    return template is not None and template.series_profile_id == series_profile_id


async def _validate_context(
    uow: CanonicalUnitOfWork,
    series_profile_id: uuid.UUID,
    episode_id: uuid.UUID | None,
    template_id: uuid.UUID | None,
) -> tuple[CanonicalEpisode | None, bool]:
    """Validate episode and template context, returning (episode, template_is_valid)."""
    episode = None
    if episode_id is not None:
        episode = await _episode_belongs_to_series(uow, episode_id, series_profile_id)

    template_is_valid = template_id is not None and await _template_belongs_to_series(
        uow, template_id, series_profile_id
    )

    return episode, template_is_valid


async def _dispatch_resolution(
    uow: CanonicalUnitOfWork,
    series_bindings: list[ReferenceBinding],
    template_bindings: list[ReferenceBinding],
    target_episode: CanonicalEpisode | None,
) -> list[ResolvedBinding]:
    """Build revision/document maps and dispatch to the appropriate resolver.

    When target_episode is None, all bindings are resolved without episode
    precedence. When target_episode is provided, series-profile bindings are
    resolved with episode-aware precedence and template bindings are merged
    without filtering.
    """
    all_bindings = series_bindings + template_bindings
    if not all_bindings:
        return []

    revision_map, document_map = await _load_revision_and_document_maps(
        uow, all_bindings
    )

    if target_episode is None:
        return _resolve_without_episode_context(
            all_bindings, revision_map, document_map
        )

    template_resolved = _resolve_without_episode_context(
        template_bindings, revision_map, document_map
    )
    series_resolved = await _resolve_with_episode_context(
        uow,
        series_bindings,
        (revision_map, document_map),
        target_episode_created_at=target_episode.created_at,
    )
    return series_resolved + template_resolved


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

    Validation:
    - If episode_id is provided, the episode must exist and belong to the
      specified series_profile_id. If validation fails, returns empty list.
    - If template_id is provided, the template must exist and belong to the
      specified series_profile_id. If validation fails, template bindings are
      skipped (treated as empty).

    Algorithm:
    1. Validate episode and template entities if provided.
    2. Collect all bindings for the series profile target.
    3. If template_id is provided and validated, collect bindings for that template.
    4. Group bindings by their parent reference document.
    5. For each document group, select the binding with the latest
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
    target_episode, template_is_valid = await _validate_context(
        uow, series_profile_id, episode_id, template_id
    )

    if episode_id is not None and target_episode is None:
        return []

    series_bindings = await uow.reference_bindings.list_for_target(
        target_kind=ReferenceBindingTargetKind.SERIES_PROFILE,
        target_id=series_profile_id,
    )

    template_bindings: list[ReferenceBinding] = []
    if template_is_valid and template_id is not None:
        template_bindings = await _load_template_bindings(uow, template_id)

    return await _dispatch_resolution(
        uow, series_bindings, template_bindings, target_episode
    )


def _snapshot_source_uri(resolved_binding: ResolvedBinding) -> str:
    """Build a stable URI for one snapshotted reference revision."""
    return (
        f"ref://{resolved_binding.document.id}/revisions/{resolved_binding.revision.id}"
    )


def _snapshot_metadata(resolved_binding: ResolvedBinding) -> dict[str, object]:
    """Build persisted provenance metadata for one resolved binding snapshot."""
    binding = resolved_binding.binding
    return {
        "binding_id": str(binding.id),
        "target_kind": binding.target_kind.value,
        "document_id": str(resolved_binding.document.id),
        "document_kind": resolved_binding.document.kind.value,
        "owner_series_profile_id": str(
            resolved_binding.document.owner_series_profile_id
        ),
        "effective_from_episode_id": (
            None
            if binding.effective_from_episode_id is None
            else str(binding.effective_from_episode_id)
        ),
    }


def _build_snapshot_source_document(
    *,
    ingestion_job_id: uuid.UUID,
    canonical_episode_id: uuid.UUID | None,
    resolved_binding: ResolvedBinding,
    created_at: dt.datetime,
) -> SourceDocument:
    """Create one provenance source-document entity from a resolved binding."""
    return SourceDocument(
        id=uuid.uuid7(),
        ingestion_job_id=ingestion_job_id,
        canonical_episode_id=canonical_episode_id,
        reference_document_revision_id=resolved_binding.revision.id,
        source_type="reference_document",
        source_uri=_snapshot_source_uri(resolved_binding),
        weight=1.0,
        content_hash=resolved_binding.revision.content_hash,
        metadata=_snapshot_metadata(resolved_binding),
        created_at=created_at,
    )


@dc.dataclass(frozen=True, slots=True)
class SnapshotContext:
    """Job-context parameters for snapshotting resolved bindings as source documents."""

    ingestion_job_id: uuid.UUID
    canonical_episode_id: uuid.UUID | None = None
    created_at: dt.datetime | None = None


async def snapshot_resolved_bindings(
    uow: CanonicalUnitOfWork,
    *,
    resolved: list[ResolvedBinding],
    context: SnapshotContext,
) -> list[SourceDocument]:
    """Persist resolved bindings as provenance source documents."""
    if not resolved:
        return []

    effective_created_at = (
        context.created_at
        if context.created_at is not None
        else dt.datetime.now(dt.UTC)
    )
    source_documents = [
        _build_snapshot_source_document(
            ingestion_job_id=context.ingestion_job_id,
            canonical_episode_id=context.canonical_episode_id,
            resolved_binding=resolved_binding,
            created_at=effective_created_at,
        )
        for resolved_binding in resolved
    ]
    for source_document in source_documents:
        await uow.source_documents.add(source_document)
    return source_documents
