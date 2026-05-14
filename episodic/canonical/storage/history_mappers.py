"""Record-to-domain mappers for canonical history entries."""

import typing as typ

from episodic.canonical.domain import (
    EpisodeTemplateHistoryEntry,
    SeriesProfileHistoryEntry,
)

from .history_models import EpisodeTemplateHistoryRecord, SeriesProfileHistoryRecord

if typ.TYPE_CHECKING:
    import collections.abc as cabc


def _history_entry_from_record(
    record: SeriesProfileHistoryRecord | EpisodeTemplateHistoryRecord,
    entity_class: (type[SeriesProfileHistoryEntry] | type[EpisodeTemplateHistoryEntry]),
    parent_id_field: str,
) -> SeriesProfileHistoryEntry | EpisodeTemplateHistoryEntry:
    """Map a history record to a history entry entity."""
    parent_id = getattr(record, parent_id_field)
    constructor = typ.cast(
        "cabc.Callable[..., SeriesProfileHistoryEntry | EpisodeTemplateHistoryEntry]",
        entity_class,
    )
    return constructor(
        id=record.id,
        revision=record.revision,
        actor=record.actor,
        note=record.note,
        snapshot=record.snapshot,
        created_at=record.created_at,
        **{parent_id_field: parent_id},
    )


def _series_profile_history_from_record(
    record: SeriesProfileHistoryRecord,
) -> SeriesProfileHistoryEntry:
    """Map a series profile history record to a domain entity."""
    return typ.cast(
        "SeriesProfileHistoryEntry",
        _history_entry_from_record(
            record=record,
            entity_class=SeriesProfileHistoryEntry,
            parent_id_field="series_profile_id",
        ),
    )


def _series_profile_history_to_record(
    entry: SeriesProfileHistoryEntry,
) -> SeriesProfileHistoryRecord:
    """Map a series profile history entry to an ORM record."""
    return SeriesProfileHistoryRecord(
        id=entry.id,
        series_profile_id=entry.series_profile_id,
        revision=entry.revision,
        actor=entry.actor,
        note=entry.note,
        snapshot=entry.snapshot,
        created_at=entry.created_at,
    )


def _episode_template_history_from_record(
    record: EpisodeTemplateHistoryRecord,
) -> EpisodeTemplateHistoryEntry:
    """Map an episode template history record to a domain entity."""
    return typ.cast(
        "EpisodeTemplateHistoryEntry",
        _history_entry_from_record(
            record=record,
            entity_class=EpisodeTemplateHistoryEntry,
            parent_id_field="episode_template_id",
        ),
    )


def _episode_template_history_to_record(
    entry: EpisodeTemplateHistoryEntry,
) -> EpisodeTemplateHistoryRecord:
    """Map an episode template history entry to an ORM record."""
    return EpisodeTemplateHistoryRecord(
        id=entry.id,
        episode_template_id=entry.episode_template_id,
        revision=entry.revision,
        actor=entry.actor,
        note=entry.note,
        snapshot=entry.snapshot,
        created_at=entry.created_at,
    )
