"""Reference-document SQLAlchemy repositories for canonical persistence."""

import typing as typ

import sqlalchemy as sa

from episodic.canonical.domain import (
    ReferenceBinding,
    ReferenceBindingTargetKind,
    ReferenceDocument,
    ReferenceDocumentKind,
    ReferenceDocumentRevision,
)
from episodic.canonical.ports import (
    ReferenceBindingRepository,
    ReferenceDocumentRepository,
    ReferenceDocumentRevisionRepository,
)

from .mappers import (
    _reference_binding_from_record,
    _reference_binding_to_record,
    _reference_document_from_record,
    _reference_document_revision_from_record,
    _reference_document_revision_to_record,
    _reference_document_to_record,
)
from .models import (
    ReferenceBindingRecord,
    ReferenceDocumentRecord,
    ReferenceDocumentRevisionRecord,
)
from .repository_base import _RepositoryBase

if typ.TYPE_CHECKING:
    import collections.abc as cabc
    import uuid


class SqlAlchemyReferenceDocumentRepository(
    _RepositoryBase, ReferenceDocumentRepository
):
    """Persist reusable reference documents using SQLAlchemy."""

    async def add(self, document: ReferenceDocument) -> None:
        """Add a reusable reference document record."""
        await self._add_record(_reference_document_to_record(document))

    async def get(self, document_id: uuid.UUID) -> ReferenceDocument | None:
        """Fetch a reusable reference document by identifier."""
        return await self._get_one_or_none(
            ReferenceDocumentRecord,
            ReferenceDocumentRecord.id == document_id,
            _reference_document_from_record,
        )

    async def list_for_series(
        self,
        series_profile_id: uuid.UUID,
        *,
        kind: ReferenceDocumentKind | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[ReferenceDocument]:
        """List reusable reference documents for one series profile."""
        where_clause = (
            ReferenceDocumentRecord.owner_series_profile_id == series_profile_id
        )
        if kind is not None:
            where_clause = sa.and_(where_clause, ReferenceDocumentRecord.kind == kind)
        statement = (
            sa
            .select(ReferenceDocumentRecord)
            .where(where_clause)
            .order_by(ReferenceDocumentRecord.created_at)
            .offset(offset)
        )
        if limit is not None:
            statement = statement.limit(limit)
        result = await self._session.execute(statement)
        return [_reference_document_from_record(row) for row in result.scalars()]

    async def list_by_ids(
        self,
        document_ids: cabc.Collection[uuid.UUID],
    ) -> list[ReferenceDocument]:
        """List reusable reference documents by identifiers."""
        if not document_ids:
            return []
        return await self._list_where(
            ReferenceDocumentRecord,
            ReferenceDocumentRecord.id.in_(list(document_ids)),
            ReferenceDocumentRecord.created_at,
            _reference_document_from_record,
        )

    async def update(self, document: ReferenceDocument) -> None:
        """Persist changes to an existing reusable reference document."""
        await self._update_where(
            ReferenceDocumentRecord,
            ReferenceDocumentRecord.id == document.id,
            {
                "owner_series_profile_id": document.owner_series_profile_id,
                "kind": document.kind,
                "lifecycle_state": document.lifecycle_state,
                "metadata_payload": document.metadata,
                "updated_at": document.updated_at,
                "lock_version": document.lock_version,
            },
        )

    async def update_with_optimistic_lock(
        self,
        document: ReferenceDocument,
        *,
        expected_lock_version: int,
    ) -> bool:
        """Persist updates when lock_version matches the expected value."""
        result = await self._session.execute(
            sa
            .update(ReferenceDocumentRecord)
            .where(
                sa.and_(
                    ReferenceDocumentRecord.id == document.id,
                    ReferenceDocumentRecord.lock_version == expected_lock_version,
                )
            )
            .values(
                owner_series_profile_id=document.owner_series_profile_id,
                kind=document.kind,
                lifecycle_state=document.lifecycle_state,
                metadata_payload=document.metadata,
                updated_at=document.updated_at,
                lock_version=document.lock_version,
            )
            .returning(ReferenceDocumentRecord.id)
        )
        return result.scalar_one_or_none() is not None


class SqlAlchemyReferenceDocumentRevisionRepository(
    _RepositoryBase, ReferenceDocumentRevisionRepository
):
    """Persist reusable reference document revisions using SQLAlchemy."""

    async def add(self, revision: ReferenceDocumentRevision) -> None:
        """Add an immutable reusable reference revision record."""
        await self._add_record(_reference_document_revision_to_record(revision))

    async def get(self, revision_id: uuid.UUID) -> ReferenceDocumentRevision | None:
        """Fetch a reusable reference revision by identifier."""
        return await self._get_one_or_none(
            ReferenceDocumentRevisionRecord,
            ReferenceDocumentRevisionRecord.id == revision_id,
            _reference_document_revision_from_record,
        )

    async def list_for_document(
        self,
        document_id: uuid.UUID,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[ReferenceDocumentRevision]:
        """List revisions for one reusable reference document."""
        statement = (
            sa
            .select(ReferenceDocumentRevisionRecord)
            .where(ReferenceDocumentRevisionRecord.reference_document_id == document_id)
            .order_by(ReferenceDocumentRevisionRecord.created_at)
            .offset(offset)
        )
        if limit is not None:
            statement = statement.limit(limit)
        result = await self._session.execute(statement)
        return [
            _reference_document_revision_from_record(row) for row in result.scalars()
        ]

    async def list_by_ids(
        self,
        revision_ids: cabc.Collection[uuid.UUID],
    ) -> list[ReferenceDocumentRevision]:
        """List reusable reference document revisions by identifiers."""
        if not revision_ids:
            return []
        return await self._list_where(
            ReferenceDocumentRevisionRecord,
            ReferenceDocumentRevisionRecord.id.in_(list(revision_ids)),
            ReferenceDocumentRevisionRecord.created_at,
            _reference_document_revision_from_record,
        )

    async def get_latest_for_document(
        self,
        document_id: uuid.UUID,
    ) -> ReferenceDocumentRevision | None:
        """Fetch the latest revision for one reusable reference document."""
        return await self._get_latest_where(
            ReferenceDocumentRevisionRecord,
            ReferenceDocumentRevisionRecord.reference_document_id == document_id,
            ReferenceDocumentRevisionRecord.created_at.desc(),
            _reference_document_revision_from_record,
        )


class SqlAlchemyReferenceBindingRepository(_RepositoryBase, ReferenceBindingRepository):
    """Persist reusable reference bindings using SQLAlchemy."""

    @staticmethod
    def _target_field(target_kind: ReferenceBindingTargetKind) -> typ.Any:  # noqa: ANN401
        """Resolve the SQLAlchemy target column for a binding target kind."""
        match target_kind:
            case ReferenceBindingTargetKind.SERIES_PROFILE:
                return ReferenceBindingRecord.series_profile_id
            case ReferenceBindingTargetKind.EPISODE_TEMPLATE:
                return ReferenceBindingRecord.episode_template_id
            case ReferenceBindingTargetKind.INGESTION_JOB:
                return ReferenceBindingRecord.ingestion_job_id
            case _:
                msg = f"Unsupported reference binding target kind: {target_kind}"
                raise ValueError(msg)

    async def add(self, binding: ReferenceBinding) -> None:
        """Add a reusable reference binding record."""
        await self._add_record(_reference_binding_to_record(binding))

    async def get(self, binding_id: uuid.UUID) -> ReferenceBinding | None:
        """Fetch a reusable reference binding by identifier."""
        return await self._get_one_or_none(
            ReferenceBindingRecord,
            ReferenceBindingRecord.id == binding_id,
            _reference_binding_from_record,
        )

    async def list_for_target(
        self,
        *,
        target_kind: ReferenceBindingTargetKind,
        target_id: uuid.UUID,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[ReferenceBinding]:
        """List reusable reference bindings for one target context."""
        target_field = self._target_field(target_kind)
        statement = (
            sa
            .select(ReferenceBindingRecord)
            .where(
                sa.and_(
                    ReferenceBindingRecord.target_kind == target_kind,
                    target_field == target_id,
                )
            )
            .order_by(ReferenceBindingRecord.created_at)
            .offset(offset)
        )
        if limit is not None:
            statement = statement.limit(limit)
        result = await self._session.execute(statement)
        return [_reference_binding_from_record(row) for row in result.scalars()]


__all__ = (
    "SqlAlchemyReferenceBindingRepository",
    "SqlAlchemyReferenceDocumentRepository",
    "SqlAlchemyReferenceDocumentRevisionRepository",
)
