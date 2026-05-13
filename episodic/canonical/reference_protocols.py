"""Repository protocols for reusable reference documents."""

import typing as typ

if typ.TYPE_CHECKING:
    import collections.abc as cabc
    import uuid

    from .domain import (
        ReferenceBinding,
        ReferenceBindingTargetKind,
        ReferenceDocument,
        ReferenceDocumentKind,
        ReferenceDocumentRevision,
    )


class ReferenceDocumentRepository(typ.Protocol):
    """Persistence interface for reusable reference documents."""

    async def add(self, document: ReferenceDocument) -> None:
        """Persist a reusable reference document."""
        raise NotImplementedError

    async def get(self, document_id: uuid.UUID) -> ReferenceDocument | None:
        """Fetch a reusable reference document by identifier."""
        raise NotImplementedError

    # Domain pagination filters are part of the repository contract.
    async def list_for_series(  # pylint: disable=too-many-arguments
        self,
        series_profile_id: uuid.UUID,
        *,
        kind: ReferenceDocumentKind | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[ReferenceDocument]:
        """List reusable reference documents owned by one series profile."""
        raise NotImplementedError

    async def list_by_ids(
        self,
        document_ids: cabc.Collection[uuid.UUID],
    ) -> list[ReferenceDocument]:
        """List reusable reference documents by identifiers."""
        raise NotImplementedError

    async def update(self, document: ReferenceDocument) -> None:
        """Persist changes to an existing reusable reference document."""
        raise NotImplementedError

    async def update_with_optimistic_lock(
        self,
        document: ReferenceDocument,
        *,
        expected_lock_version: int,
    ) -> bool:
        """Update with optimistic locking and return whether the row matched."""
        raise NotImplementedError


class ReferenceDocumentRevisionRepository(typ.Protocol):
    """Persistence interface for reusable reference document revisions."""

    async def add(self, revision: ReferenceDocumentRevision) -> None:
        """Persist a reusable reference document revision."""
        raise NotImplementedError

    async def get(
        self,
        revision_id: uuid.UUID,
    ) -> ReferenceDocumentRevision | None:
        """Fetch a reusable reference document revision by identifier."""
        raise NotImplementedError

    async def list_for_document(
        self,
        document_id: uuid.UUID,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[ReferenceDocumentRevision]:
        """List immutable revisions for one reusable reference document."""
        raise NotImplementedError

    async def list_by_ids(
        self,
        revision_ids: cabc.Collection[uuid.UUID],
    ) -> list[ReferenceDocumentRevision]:
        """List reusable reference document revisions by identifiers."""
        raise NotImplementedError

    async def get_latest_for_document(
        self,
        document_id: uuid.UUID,
    ) -> ReferenceDocumentRevision | None:
        """Fetch the latest immutable revision for a reference document."""
        raise NotImplementedError


class ReferenceBindingRepository(typ.Protocol):
    """Persistence interface for reusable reference bindings."""

    async def add(self, binding: ReferenceBinding) -> None:
        """Persist a reusable reference binding."""
        raise NotImplementedError

    async def get(self, binding_id: uuid.UUID) -> ReferenceBinding | None:
        """Fetch a reusable reference binding by identifier."""
        raise NotImplementedError

    # Domain pagination filters are part of the repository contract.
    async def list_for_target(  # pylint: disable=too-many-arguments
        self,
        *,
        target_kind: ReferenceBindingTargetKind,
        target_id: uuid.UUID,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[ReferenceBinding]:
        """List bindings for one target context."""
        raise NotImplementedError
