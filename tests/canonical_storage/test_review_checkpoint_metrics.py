"""Metric coverage for the SQL review-checkpoint store.

Two properties are load-bearing because the metric names carry them. The
open-checkpoint gauge is emitted with an empty label set, so it must be a global
count: a per-run value under that label would be attributed to whichever run
wrote last, and resolving one run's final checkpoint would erase another run's
backlog. The terminal-conflict counter exists to expose retry storms, so it must
see both refusal routes -- the domain precondition and a lost compare-and-set --
not only the conditional-update one.
"""

import datetime as dt
import typing as typ

import pytest
import sqlalchemy as sa

from episodic.canonical.domain import (
    CheckpointAction,
    CheckpointResponse,
    CheckpointStatus,
)
from episodic.canonical.generation_run_errors import CheckpointAlreadyTerminal
from episodic.canonical.storage import SqlAlchemyUnitOfWork
from episodic.canonical.storage.review_checkpoint_models import ReviewCheckpointRecord
from episodic.canonical.storage.review_checkpoints import (
    SqlAlchemyReviewCheckpointStore,
)
from tests.canonical_storage._generation_run_support import (
    NOW,
    commit_run_and_checkpoint,
    make_checkpoint,
    make_generation_run,
    persist_generation_run_prerequisites,
)

if typ.TYPE_CHECKING:
    import collections.abc as cabc
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_METRIC_CREATED = "review_checkpoint_created_total"
_METRIC_RESOLVED = "review_checkpoint_resolved_total"
_METRIC_OPEN = "review_checkpoint_open_gauge"
_METRIC_TERMINAL_CONFLICT = "review_checkpoint_terminal_conflict_total"


class _RecordingValueMetrics:
    """Capture counters and scalar values for store-level assertions."""

    def __init__(self) -> None:
        self.counters: list[tuple[str, dict[str, str]]] = []
        self.values: list[tuple[str, float, dict[str, str]]] = []

    def increment_counter(
        self,
        name: str,
        *,
        labels: cabc.Mapping[str, str],
    ) -> None:
        """Record a counter increment."""
        self.counters.append((name, dict(labels)))

    def observe_latency_ms(
        self,
        name: str,
        value: float,
        *,
        labels: cabc.Mapping[str, str],
    ) -> None:
        """Accept a latency observation; the checkpoint store emits none."""
        del name, value, labels

    def observe_value(
        self,
        name: str,
        value: float,
        *,
        labels: cabc.Mapping[str, str],
    ) -> None:
        """Record a scalar observation."""
        self.values.append((name, value, dict(labels)))

    def counter_names(self) -> list[str]:
        """Return counter names in emission order."""
        return [name for name, _ in self.counters]

    def value_series(self, name: str) -> list[float]:
        """Return one metric's observed values in emission order."""
        return [value for metric, value, _ in self.values if metric == name]


def _approval() -> CheckpointResponse:
    """Return a deterministic reviewer approval."""
    return CheckpointResponse(
        action=CheckpointAction.APPROVE,
        payload={"approved": True},
        responded_at=NOW + dt.timedelta(minutes=1),
        responded_by="reviewer@example.com",
    )


async def _resolve_row_externally(
    session: AsyncSession,
    checkpoint_id: uuid.UUID,
) -> None:
    """Resolve a stored row the way a different process would.

    ``synchronize_session=False`` leaves this session's copy untouched, which is
    the state a second writer produces. Going through the ORM would refresh the
    copy and remove the lost-race condition under test.
    """
    await session.execute(
        sa
        .update(ReviewCheckpointRecord)
        .where(ReviewCheckpointRecord.id == checkpoint_id)
        .values(
            status=CheckpointStatus.TIMED_OUT.value,
            resolved_at=NOW + dt.timedelta(minutes=2),
            responded_by="system",
        )
        .execution_options(synchronize_session=False)
    )


@pytest.mark.asyncio
async def test_open_gauge_reports_the_global_backlog(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Resolving one run's only checkpoint still reports another run's backlog."""
    first_run = make_generation_run()
    second_run = make_generation_run()
    await persist_generation_run_prerequisites(session_factory, first_run, second_run)
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        await uow.generation_runs.create_run(first_run)
        await uow.generation_runs.create_run(second_run)
        await uow.commit()

    metrics = _RecordingValueMetrics()
    async with session_factory() as session:
        store = SqlAlchemyReviewCheckpointStore(session, metrics=metrics)
        first = await store.create_checkpoint(make_checkpoint(first_run.id))
        await session.commit()
        await store.create_checkpoint(make_checkpoint(second_run.id))
        await session.commit()
        await store.respond_to_checkpoint(first.id, response=_approval())
        await session.commit()

    assert metrics.counter_names() == [
        _METRIC_CREATED,
        _METRIC_CREATED,
        _METRIC_RESOLVED,
    ], metrics.counters
    assert metrics.value_series(_METRIC_OPEN) == [1.0, 2.0, 1.0], (
        "the gauge must count every run's open checkpoints, not the last run's"
    )


@pytest.mark.asyncio
async def test_domain_rejection_counts_as_a_terminal_conflict(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Responding twice increments the counter on the second, refused call."""
    committed = await commit_run_and_checkpoint(session_factory)
    metrics = _RecordingValueMetrics()

    async with session_factory() as session:
        store = SqlAlchemyReviewCheckpointStore(session, metrics=metrics)
        await store.respond_to_checkpoint(committed.checkpoint_id, response=_approval())
        await session.commit()
        assert metrics.counter_names().count(_METRIC_TERMINAL_CONFLICT) == 0, (
            "the first response succeeds, so nothing has conflicted yet"
        )
        with pytest.raises(CheckpointAlreadyTerminal):
            await store.respond_to_checkpoint(
                committed.checkpoint_id,
                response=_approval(),
            )
        await session.rollback()

    assert metrics.counter_names().count(_METRIC_TERMINAL_CONFLICT) == 1, (
        "an ordinary terminal rejection is a retry storm and must be counted"
    )


@pytest.mark.asyncio
async def test_lost_compare_and_set_counts_as_a_terminal_conflict(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A compare-and-set that loses to another writer increments the counter."""
    committed = await commit_run_and_checkpoint(session_factory)
    metrics = _RecordingValueMetrics()

    async with session_factory() as session:
        store = SqlAlchemyReviewCheckpointStore(session, metrics=metrics)
        # Hold the stale instance, as `_resolve` does: identity-map entries are
        # weak, so an unheld copy is collected and re-read as the true value.
        pinned = await session.get(ReviewCheckpointRecord, committed.checkpoint_id)
        assert pinned is not None, "the committed checkpoint must be readable"
        assert pinned.status is CheckpointStatus.CREATED, (
            "the session must begin by holding the row as created"
        )
        await _resolve_row_externally(session, committed.checkpoint_id)

        with pytest.raises(CheckpointAlreadyTerminal):
            await store.respond_to_checkpoint(
                committed.checkpoint_id,
                response=_approval(),
            )
        await session.rollback()

    assert metrics.counter_names().count(_METRIC_TERMINAL_CONFLICT) == 1, (
        "the conditional-update conflict route must keep counting"
    )
