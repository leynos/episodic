"""Entity loaders and binding serialisation for structured-brief assembly.

Provides helpers to bulk-load ``ReferenceDocumentRevision`` and
``ReferenceDocument`` entities from the unit of work, validate that all
expected IDs were resolved, and serialise a collection of
``ReferenceBinding`` objects into brief payload mappings after verifying
document ownership.

Does not perform reference-document resolution or episode-aware logic; those
responsibilities belong to ``_brief_reference_documents``. Consumed by
``brief`` and ``_brief_reference_documents``; not part of the public package
API.
"""

import typing as typ

from .types import EntityNotFoundError

if typ.TYPE_CHECKING:
    import collections.abc as cabc
    import uuid

    from episodic.canonical.domain import (
        EpisodeTemplate,
        JsonMapping,
        ReferenceBinding,
        ReferenceBindingTargetKind,
        ReferenceDocument,
        ReferenceDocumentRevision,
    )
    from episodic.canonical.unit_of_work_protocols import CanonicalUnitOfWork


def _raise_if_missing_ids(
    *,
    expected_ids: set[uuid.UUID],
    found_ids: set[uuid.UUID],
    label: str,
) -> None:
    """Raise ValueError when any expected identifier is missing."""
    missing_ids = expected_ids - found_ids
    if not missing_ids:
        return
    missing_id = next(iter(missing_ids))
    msg = f"{label}: {missing_id}"
    raise ValueError(msg)


async def _load_revisions_by_id(
    *,
    uow: CanonicalUnitOfWork,
    bindings: list[ReferenceBinding],
) -> dict[uuid.UUID, ReferenceDocumentRevision]:
    """Load revisions referenced by bindings and fail on missing identifiers."""
    revision_ids = {binding.reference_document_revision_id for binding in bindings}
    revisions = await uow.reference_document_revisions.list_by_ids(revision_ids)
    revisions_by_id = {revision.id: revision for revision in revisions}
    _raise_if_missing_ids(
        expected_ids=revision_ids,
        found_ids=set(revisions_by_id),
        label="Reference binding points to missing revision",
    )
    return revisions_by_id


async def _load_documents_by_id(
    *,
    uow: CanonicalUnitOfWork,
    revisions: cabc.Iterable[ReferenceDocumentRevision],
) -> dict[uuid.UUID, ReferenceDocument]:
    """Load documents referenced by revisions and fail on missing identifiers."""
    document_ids = {revision.reference_document_id for revision in revisions}
    documents = await uow.reference_documents.list_by_ids(document_ids)
    documents_by_id = {document.id: document for document in documents}
    _raise_if_missing_ids(
        expected_ids=document_ids,
        found_ids=set(documents_by_id),
        label="Reference revision points to missing document",
    )
    return documents_by_id


def _serialize_bindings_for_owner(
    *,
    bindings: list[ReferenceBinding],
    revisions_by_id: dict[uuid.UUID, ReferenceDocumentRevision],
    documents_by_id: dict[uuid.UUID, ReferenceDocument],
    owner_series_profile_id: uuid.UUID,
) -> list[JsonMapping]:
    """Serialize bindings after validating owner alignment for each document."""
    from ._brief_serializers import _serialize_reference_document_for_brief

    serialized: list[JsonMapping] = []
    for binding in bindings:
        revision = revisions_by_id[binding.reference_document_revision_id]
        document = documents_by_id[revision.reference_document_id]
        if document.owner_series_profile_id != owner_series_profile_id:
            msg = (
                f"Reference document {document.id} does not belong to requested "
                f"series profile {owner_series_profile_id}."
            )
            raise ValueError(msg)
        serialized.append(
            _serialize_reference_document_for_brief(
                binding=binding,
                document=document,
                revision=revision,
            )
        )
    return serialized


async def _load_reference_documents_for_target(
    uow: CanonicalUnitOfWork,
    *,
    target_kind: ReferenceBindingTargetKind,
    target_id: uuid.UUID,
    owner_series_profile_id: uuid.UUID,
) -> list[JsonMapping]:
    """Load serialized reference documents for one binding target."""
    bindings = await uow.reference_bindings.list_for_target(
        target_kind=target_kind,
        target_id=target_id,
    )
    if not bindings:
        return []

    revisions_by_id = await _load_revisions_by_id(
        uow=uow,
        bindings=bindings,
    )
    documents_by_id = await _load_documents_by_id(
        uow=uow,
        revisions=revisions_by_id.values(),
    )
    return _serialize_bindings_for_owner(
        bindings=bindings,
        revisions_by_id=revisions_by_id,
        documents_by_id=documents_by_id,
        owner_series_profile_id=owner_series_profile_id,
    )


async def _load_template_items_for_brief(
    uow: CanonicalUnitOfWork,
    *,
    profile_id: uuid.UUID,
    template_id: uuid.UUID | None,
) -> list[tuple[EpisodeTemplate, int]]:
    """Load template and revision pairs for structured brief rendering."""
    from .services import get_entity_with_revision, list_entities_with_revisions

    if template_id is None:
        items = await list_entities_with_revisions(
            uow,
            kind="episode_template",
            series_profile_id=profile_id,
        )
        return [
            (typ.cast("EpisodeTemplate", template), revision)
            for template, revision in items
        ]

    template_obj, template_revision = await get_entity_with_revision(
        uow,
        entity_id=template_id,
        kind="episode_template",
    )
    template = typ.cast("EpisodeTemplate", template_obj)
    if template.series_profile_id != profile_id:
        msg = (
            f"Episode template {template.id} does not belong to "
            f"series profile {profile_id}."
        )
        raise EntityNotFoundError(msg, entity_id=str(template.id))
    return [(template, template_revision)]
