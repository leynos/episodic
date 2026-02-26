"""Types, protocols, and exceptions for profile/template services.

This module defines typed request/data objects, repository/history protocols,
and domain-specific exceptions used by profile/template service functions.
Import these symbols when building adapters, implementing repositories, or
handling canonical profile/template errors.

Examples
--------
>>> from episodic.canonical.profile_templates.types import EntityNotFoundError
>>> raise EntityNotFoundError("Series profile <id> not found.")
"""

import collections.abc as cabc
import dataclasses as dc
import enum
import typing as typ
import uuid

if typ.TYPE_CHECKING:
    from episodic.canonical.domain import (
        EpisodeTemplate,
        EpisodeTemplateHistoryEntry,
        JsonMapping,
        SeriesProfile,
        SeriesProfileHistoryEntry,
    )

type LatestRevisionsMap = dict[uuid.UUID, int]
type BulkLatestRevisionsFn = cabc.Callable[
    [cabc.Collection[uuid.UUID]],
    cabc.Awaitable[LatestRevisionsMap],
]


@dc.dataclass(frozen=True, slots=True)
class AuditMetadata:
    """Audit metadata for versioned operations.

    Attributes
    ----------
    actor : str | None
        Optional identifier for the actor performing the operation.
    note : str | None
        Optional free-form note attached to the operation.
    """

    actor: str | None
    note: str | None


@dc.dataclass(frozen=True, slots=True)
class SeriesProfileData:
    """Entity data for series profile operations.

    Attributes
    ----------
    title : str
        Human-readable profile title.
    description : str | None
        Optional longer profile description.
    configuration : JsonMapping
        Profile configuration payload consumed by downstream workflows.
    """

    title: str
    description: str | None
    configuration: JsonMapping


@dc.dataclass(frozen=True, slots=True)
class SeriesProfileCreateData(SeriesProfileData):
    """Entity data for creating a series profile.

    Attributes
    ----------
    slug : str
        Stable profile slug used for unique identification.
    """

    slug: str


@dc.dataclass(frozen=True, slots=True)
class SeriesProfileUpdateFields(SeriesProfileData):
    """Entity data for updating a series profile.

    This subclass is intentionally nominal and carries the same fields as
    ``SeriesProfileData`` so update call sites can express intent explicitly.

    Attributes
    ----------
    title : str
        Updated profile title.
    description : str | None
        Updated profile description.
    configuration : JsonMapping
        Updated profile configuration payload.
    """


@dc.dataclass(frozen=True, slots=True)
class EpisodeTemplateUpdateFields:
    """Entity data for updating an episode template.

    Attributes
    ----------
    title : str
        Updated template title.
    description : str | None
        Updated template description.
    structure : JsonMapping
        Updated JSON template structure payload.
    """

    title: str
    description: str | None
    structure: JsonMapping


@dc.dataclass(frozen=True, slots=True)
class EpisodeTemplateData:
    """Data for creating or updating an episode template.

    Attributes
    ----------
    slug : str
        Stable slug identifying the template within a profile.
    title : str
        Human-readable template title.
    description : str | None
        Optional longer template description.
    structure : JsonMapping
        JSON structure that defines template segments.
    """

    slug: str
    title: str
    description: str | None
    structure: JsonMapping


@dc.dataclass(frozen=True, slots=True)
class UpdateSeriesProfileRequest:
    """Request to update a series profile with optimistic locking.

    Attributes
    ----------
    profile_id : uuid.UUID
        Identifier of the profile to update.
    expected_revision : int
        Revision expected by the caller for optimistic locking.
    data : SeriesProfileUpdateFields
        Updated profile field values.
    audit : AuditMetadata
        Actor metadata captured for history tracking.
    """

    profile_id: uuid.UUID
    expected_revision: int
    data: SeriesProfileUpdateFields
    audit: AuditMetadata


@dc.dataclass(frozen=True, slots=True)
class UpdateEpisodeTemplateRequest:
    """Request to update an episode template with optimistic locking.

    Attributes
    ----------
    template_id : uuid.UUID
        Identifier of the template to update.
    expected_revision : int
        Revision expected by the caller for optimistic locking.
    data : EpisodeTemplateUpdateFields
        Updated template field values.
    audit : AuditMetadata
        Actor metadata captured for history tracking.
    """

    template_id: uuid.UUID
    expected_revision: int
    data: EpisodeTemplateUpdateFields
    audit: AuditMetadata


class ProfileTemplateError(Exception):
    """Base exception with structured metadata for profile/template services."""

    error_code: typ.ClassVar[str] = "profile_template_error"
    default_retryable: typ.ClassVar[bool] = False

    code: str
    entity_id: str | None
    retryable: bool

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        entity_id: str | None = None,
        retryable: bool | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code if code is not None else type(self).error_code
        self.entity_id = entity_id
        self.retryable = (
            type(self).default_retryable if retryable is None else retryable
        )


class EntityNotFoundError(ProfileTemplateError):
    """Raised when an expected profile or template does not exist."""

    error_code: typ.ClassVar[str] = "entity_not_found"


class RevisionConflictError(ProfileTemplateError):
    """Raised when optimistic-lock revision preconditions are not met."""

    error_code: typ.ClassVar[str] = "revision_conflict"
    default_retryable: typ.ClassVar[bool] = True


class EntityKind(enum.StrEnum):
    """Supported entity kinds for shared profile/template services."""

    SERIES_PROFILE = "series_profile"
    EPISODE_TEMPLATE = "episode_template"


class _RevisionedEntry(typ.Protocol):
    """Protocol for history entries that expose a revision."""

    revision: int


class _VersionedEntity(typ.Protocol):
    """Protocol for versioned entities with stable identifiers."""

    id: uuid.UUID


class _EntityRepository[EntityT: _VersionedEntity](typ.Protocol):
    """Protocol for repositories that update versioned entities."""

    async def get(self, entity_id: uuid.UUID, /) -> EntityT | None: ...

    async def update(self, entity: EntityT, /) -> None: ...


class _HistoryRepository[HistoryT](typ.Protocol):
    """Protocol for repositories that persist history entries."""

    async def add(self, entry: HistoryT, /) -> None: ...


class _SeriesProfileRepository(typ.Protocol):
    """Protocol for series-profile repository read operations."""

    async def get(self, entity_id: uuid.UUID, /) -> SeriesProfile | None: ...

    async def list(self) -> cabc.Sequence[SeriesProfile]: ...


class _EpisodeTemplateRepository(typ.Protocol):
    """Protocol for episode-template repository read operations."""

    async def get(self, entity_id: uuid.UUID, /) -> EpisodeTemplate | None: ...

    async def list(
        self,
        series_profile_id: uuid.UUID | None,
    ) -> cabc.Sequence[EpisodeTemplate]: ...


class _SeriesProfileHistoryRepository(typ.Protocol):
    """Protocol for series-profile history repository read operations."""

    async def get_latest_for_profile(
        self,
        profile_id: uuid.UUID,
        /,
    ) -> SeriesProfileHistoryEntry | None: ...

    async def list_for_profile(
        self,
        profile_id: uuid.UUID,
        /,
    ) -> list[SeriesProfileHistoryEntry]: ...

    get_latest_revisions_for_profiles: BulkLatestRevisionsFn


class _EpisodeTemplateHistoryRepository(typ.Protocol):
    """Protocol for episode-template history repository read operations."""

    async def get_latest_for_template(
        self,
        template_id: uuid.UUID,
        /,
    ) -> EpisodeTemplateHistoryEntry | None: ...

    async def list_for_template(
        self,
        template_id: uuid.UUID,
        /,
    ) -> list[EpisodeTemplateHistoryEntry]: ...

    get_latest_revisions_for_templates: BulkLatestRevisionsFn
