"""Series profile, TEI header, and episode template domain models."""

import dataclasses as dc
import typing as typ

if typ.TYPE_CHECKING:
    import datetime as dt
    import uuid

    from .domain_enums import JsonMapping


@dc.dataclass(frozen=True, slots=True)
class SeriesProfile:
    """Series metadata required for canonical ingestion."""

    id: uuid.UUID
    slug: str
    title: str
    description: str | None
    configuration: JsonMapping
    guardrails: JsonMapping
    created_at: dt.datetime
    updated_at: dt.datetime


@dc.dataclass(frozen=True, slots=True)
class TeiHeader:
    """Parsed TEI header payload."""

    id: uuid.UUID
    title: str
    payload: JsonMapping
    raw_xml: str
    created_at: dt.datetime
    updated_at: dt.datetime


@dc.dataclass(frozen=True, slots=True)
class EpisodeTemplate:
    """Episode template metadata for structured brief generation.

    Attributes
    ----------
    id : uuid.UUID
        Primary key for the episode template.
    series_profile_id : uuid.UUID
        Foreign key to the owning series profile.
    slug : str
        Stable slug identifier unique within a profile.
    title : str
        Human-readable template title.
    description : str | None
        Optional longer template description.
    structure : JsonMapping
        JSON structure describing template sections.
    guardrails : JsonMapping
        Persisted LLM guardrail configuration for this template.
    created_at : dt.datetime
        Timestamp when the template was created.
    updated_at : dt.datetime
        Timestamp when the template was last updated.
    """

    id: uuid.UUID
    series_profile_id: uuid.UUID
    slug: str
    title: str
    description: str | None
    structure: JsonMapping
    guardrails: JsonMapping
    created_at: dt.datetime
    updated_at: dt.datetime


@dc.dataclass(frozen=True, slots=True)
class SeriesProfileHistoryEntry:
    """Immutable change-history entry for a series profile.

    Attributes
    ----------
    id : uuid.UUID
        Primary key for the history entry.
    series_profile_id : uuid.UUID
        Foreign key to the series profile.
    revision : int
        Monotonically increasing revision number.
    actor : str | None
        Optional identifier for the actor who made the change.
    note : str | None
        Optional free-form note describing the change.
    snapshot : JsonMapping
        Snapshot payload of the profile state at this revision.
    created_at : dt.datetime
        Timestamp when the history entry was created.
    """

    id: uuid.UUID
    series_profile_id: uuid.UUID
    revision: int
    actor: str | None
    note: str | None
    snapshot: JsonMapping
    created_at: dt.datetime


@dc.dataclass(frozen=True, slots=True)
class EpisodeTemplateHistoryEntry:
    """Immutable change-history entry for an episode template.

    Attributes
    ----------
    id : uuid.UUID
        Primary key for the history entry.
    episode_template_id : uuid.UUID
        Foreign key to the episode template.
    revision : int
        Monotonically increasing revision number.
    actor : str | None
        Optional identifier for the actor who made the change.
    note : str | None
        Optional free-form note describing the change.
    snapshot : JsonMapping
        Snapshot payload of the template state at this revision.
    created_at : dt.datetime
        Timestamp when the history entry was created.
    """

    id: uuid.UUID
    episode_template_id: uuid.UUID
    revision: int
    actor: str | None
    note: str | None
    snapshot: JsonMapping
    created_at: dt.datetime
