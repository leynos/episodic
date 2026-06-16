"""Unit tests for profile/template service helpers.

These tests exercise `_update_versioned_entity` in isolation with lightweight
doubles so the transactional contract can be pinned without a database. The
focus is the conflict path: when the storage adapter translates a duplicate
``(parent_id, revision)`` insert into ``RevisionConflictError`` after the
entity update has already executed in the outer transaction, the helper must
roll the unit of work back so the orphaned entity update can never be
committed.
"""

from __future__ import annotations

import dataclasses as dc
import datetime as dt
import typing as typ
import uuid

import pytest

from episodic.canonical.domain import SeriesProfile, SeriesProfileHistoryEntry
from episodic.canonical.profile_templates.helpers import _update_versioned_entity
from episodic.canonical.profile_templates.types import (
    AuditMetadata,
    RevisionConflictError,
)

if typ.TYPE_CHECKING:
    from episodic.canonical.unit_of_work_protocols import CanonicalUnitOfWork


@dc.dataclass(slots=True)
class _RecordingUnitOfWork:
    """Unit-of-work double recording commit/rollback calls."""

    committed: bool = False
    rolled_back: bool = False

    async def commit(self) -> None:
        """Record that the transaction was committed."""
        self.committed = True

    async def rollback(self) -> None:
        """Record that the transaction was rolled back."""
        self.rolled_back = True


class _RecordingEntityRepository:
    """Entity repository double returning a fixed entity and recording updates."""

    def __init__(self, entity: SeriesProfile) -> None:
        self._entity = entity
        self.updated: list[SeriesProfile] = []

    async def get(self, entity_id: uuid.UUID, /) -> SeriesProfile | None:
        """Return the preconfigured entity regardless of identifier."""
        return self._entity

    async def update(self, entity: SeriesProfile, /) -> None:
        """Record that the entity update ran in the outer transaction."""
        self.updated.append(entity)


class _ConflictingHistoryRepository:
    """History repository double raising a translated revision conflict."""

    def __init__(self, entity_id: uuid.UUID) -> None:
        self._entity_id = entity_id
        self.attempts: list[SeriesProfileHistoryEntry] = []

    async def add(self, entry: SeriesProfileHistoryEntry, /) -> None:
        """Record the attempt, then raise as the storage adapter would."""
        self.attempts.append(entry)
        msg = "Revision conflict: concurrent history insert detected."
        raise RevisionConflictError(msg, entity_id=str(self._entity_id))


@dc.dataclass(frozen=True, slots=True)
class _RevisionStub:
    """Minimal latest-revision stand-in exposing only ``revision``."""

    revision: int


def _series_profile() -> SeriesProfile:
    """Build a minimal series profile for the helper under test."""
    now = dt.datetime.now(dt.UTC)
    return SeriesProfile(
        id=uuid.uuid4(),
        slug="conflict-profile",
        title="Conflict Profile",
        description=None,
        configuration={},
        guardrails={},
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_update_versioned_entity_rolls_back_on_translated_conflict() -> None:
    """A translated history conflict rolls back the entity update too.

    The optimistic pre-check passes, the entity update executes, and only then
    does the history insert collide. The helper must roll the unit of work back
    so a caller cannot commit the entity update without its history revision.
    """
    profile = _series_profile()
    uow = _RecordingUnitOfWork()
    entity_repo = _RecordingEntityRepository(profile)
    history_repo = _ConflictingHistoryRepository(profile.id)

    async def fetch_latest(_entity_id: uuid.UUID) -> _RevisionStub:  # noqa: RUF029  # awaited via the fetch_latest contract, so it must be a coroutine
        return _RevisionStub(revision=1)

    def update_fields(entity: SeriesProfile, _now: dt.datetime) -> SeriesProfile:
        return entity

    def create_snapshot(_entity: SeriesProfile) -> dict[str, object]:
        return {}

    with pytest.raises(RevisionConflictError):
        await _update_versioned_entity(
            typ.cast("CanonicalUnitOfWork", uow),
            entity_id=profile.id,
            expected_revision=1,
            entity_label="Series profile",
            entity_repo=entity_repo,
            history_repo=history_repo,
            fetch_latest=fetch_latest,
            history_entry_class=SeriesProfileHistoryEntry,
            entity_id_field="series_profile_id",
            update_fields=update_fields,
            create_snapshot=create_snapshot,
            audit=AuditMetadata(actor="editor@example.com", note="Concurrent edit"),
        )

    assert entity_repo.updated, "expected the entity update to run before the conflict"
    assert history_repo.attempts, "expected the history insert to be attempted"
    assert uow.rolled_back, "expected the unit of work to roll back on conflict"
    assert not uow.committed, "expected no commit once the conflict propagates"
