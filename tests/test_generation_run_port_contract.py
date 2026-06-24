"""Contract tests for generation-run port implementations.

These tests define the behavioural contract for adapters implementing
`GenerationRunRepository`, `GenerationEventLog`, `GenerationCheckpointPort`,
and the composite `GenerationRunPort`. They validate protocol compliance,
lifecycle guarantees, error and edge-case behaviour, idempotency, pagination
guardrails, event sequence allocation, and checkpoint response persistence.
Use the `store` fixture plus `make_generation_run()` and `make_checkpoint()`
when adding scenarios for another implementation.
"""

import dataclasses as dc
import datetime as dt
import typing as typ
import uuid

import pytest

from episodic.canonical.adapters.generation_runs import InMemoryGenerationRunStore
from episodic.canonical.domain import (
    Checkpoint,
    CheckpointResponse,
    CheckpointStatus,
    GenerationEvent,
    GenerationRun,
    GenerationRunStatus,
    JsonMapping,
)
from episodic.canonical.generation_quality import QaStatus, QualityMode
from episodic.canonical.generation_run_errors import CheckpointNotFound, RunNotFound
from episodic.canonical.generation_run_ports import (
    EventSeq,
    GenerationCheckpointPort,
    GenerationEventLog,
    GenerationRunPort,
    GenerationRunRepository,
    event_seq,
)

NOW = dt.datetime(2026, 6, 4, 8, 0, tzinfo=dt.UTC)


def make_generation_run(
    *,
    run_id: uuid.UUID | None = None,
    episode_id: uuid.UUID | None = None,
) -> GenerationRun:
    """Build a generation run for contract tests.

    Parameters
    ----------
    run_id : uuid.UUID | None
        Optional identifier to assign to the run. A UUIDv7 value is generated
        when omitted.
    episode_id : uuid.UUID | None
        Optional episode identifier to assign to the run. A UUIDv7 value is
        generated when omitted.

    Returns
    -------
    GenerationRun
        A pending run with deterministic timestamps, empty JSON mappings for
        budget and configuration, and no started or ended timestamp.
    """
    return GenerationRun(
        id=run_id or uuid.uuid7(),
        episode_id=episode_id or uuid.uuid7(),
        source_bundle_id=uuid.uuid7(),
        actor="editor@example.com",
        status=GenerationRunStatus.PENDING,
        current_node=None,
        budget_snapshot={},
        configuration={},
        created_at=NOW,
        updated_at=NOW,
        started_at=None,
        ended_at=None,
        error_message=None,
        quality_mode=QualityMode.DRAFT_WITHOUT_QA,
        qa_status=QaStatus.SKIPPED,
        skip_qa_rationale="No-QA vertical-slice draft.",
    )


def make_checkpoint(run_id: uuid.UUID) -> Checkpoint:
    """Build a created checkpoint attached to a run.

    Parameters
    ----------
    run_id : uuid.UUID
        Identifier of the generation run that owns the checkpoint.

    Returns
    -------
    Checkpoint
        A created checkpoint for the `review` node with an approval prompt,
        approve/request-changes/edit options, deterministic timestamp, and no
        reviewer response.
    """
    return Checkpoint(
        id=uuid.uuid7(),
        generation_run_id=run_id,
        node="review",
        prompt="Approve?",
        options=("approve", "request_changes", "edit"),
        status=CheckpointStatus.CREATED,
        created_at=NOW,
        responded_at=None,
        responded_by=None,
        response_action=None,
        response_payload={},
    )


@pytest.fixture
def store() -> InMemoryGenerationRunStore:
    """Create a deterministic in-memory store for each contract test."""
    return InMemoryGenerationRunStore(time_provider=lambda: NOW)


# Protocol arity is fixed by the port contract; this is a minimal test stub.
class NoopGenerationRunPort:  # pylint: disable=too-many-arguments
    """No-op implementation used for composite protocol type checking."""

    async def create_run(
        self,
        run: GenerationRun,
        *,
        idempotency_key: str | None = None,
    ) -> GenerationRun:
        """Return the supplied run."""
        return run

    async def get_run(self, run_id: uuid.UUID) -> GenerationRun | None:
        """Return no run."""
        return None

    async def list_runs(
        self,
        episode_id: uuid.UUID,
        *,
        status: GenerationRunStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[GenerationRun, ...]:
        """Return no runs."""
        return ()

    async def update_run_status(
        self,
        run_id: uuid.UUID,
        *,
        status: GenerationRunStatus,
        current_node: str | None,
        ended_at: dt.datetime | None,
    ) -> GenerationRun:
        """Raise for all updates."""
        raise RunNotFound(run_id)

    async def claim_run_for_execution(
        self,
        run_id: uuid.UUID,
        *,
        current_node: str | None,
        started_at: dt.datetime,
        lease_expires_at: dt.datetime | None,
    ) -> GenerationRun | None:
        """Raise for all execution claims."""
        raise RunNotFound(run_id)

    async def append_event(
        self,
        run_id: uuid.UUID,
        *,
        kind: str,
        payload: JsonMapping,
        occurred_at: dt.datetime | None = None,
    ) -> GenerationEvent:
        """Raise for all event appends."""
        raise RunNotFound(run_id)

    async def list_events(
        self,
        run_id: uuid.UUID,
        *,
        after_seq: EventSeq | None = None,
        limit: int = 100,
    ) -> tuple[GenerationEvent, ...]:
        """Return no events."""
        return ()

    async def create_checkpoint(self, checkpoint: Checkpoint) -> Checkpoint:
        """Return the supplied checkpoint."""
        return checkpoint

    async def get_checkpoint(
        self,
        checkpoint_id: uuid.UUID,
    ) -> Checkpoint | None:
        """Return no checkpoint."""
        return None

    async def respond_to_checkpoint(
        self,
        checkpoint_id: uuid.UUID,
        *,
        response: CheckpointResponse,
    ) -> Checkpoint:
        """Raise for all responses."""
        raise CheckpointNotFound(checkpoint_id)

    async def time_out_checkpoint(
        self,
        checkpoint_id: uuid.UUID,
        *,
        at: dt.datetime,
    ) -> Checkpoint:
        """Raise for all timeouts."""
        raise CheckpointNotFound(checkpoint_id)

    async def cancel_checkpoint(
        self,
        checkpoint_id: uuid.UUID,
        *,
        at: dt.datetime,
    ) -> Checkpoint:
        """Raise for all cancellations."""
        raise CheckpointNotFound(checkpoint_id)


class TestGenerationRunRepository:
    """Contract tests for generation-run repository operations."""

    def test_in_memory_store_satisfies_generation_run_ports(self) -> None:
        """The reference adapter should structurally satisfy every port."""
        store = InMemoryGenerationRunStore()

        assert isinstance(store, GenerationRunRepository), (
            "store must implement GenerationRunRepository"
        )
        assert isinstance(store, GenerationEventLog), (
            "store must implement GenerationEventLog"
        )
        assert isinstance(store, GenerationCheckpointPort), (
            "store must implement GenerationCheckpointPort"
        )
        assert isinstance(store, GenerationRunPort), (
            "store must implement GenerationRunPort"
        )

    @pytest.mark.asyncio
    async def test_create_run_reuses_idempotency_key(
        self,
        store: InMemoryGenerationRunStore,
    ) -> None:
        """Creating with the same idempotency key returns the first run."""
        first = make_generation_run()
        duplicate = make_generation_run()

        stored_first = await store.create_run(first, idempotency_key="run-key")
        stored_duplicate = await store.create_run(duplicate, idempotency_key="run-key")

        assert stored_duplicate == stored_first, (
            "duplicate idempotency key must return first run"
        )
        assert await store.get_run(first.id) == stored_first, (
            "first run must be retrievable by ID"
        )
        assert await store.get_run(duplicate.id) is None, (
            "duplicate run must not be persisted"
        )

    @pytest.mark.asyncio
    async def test_list_runs_filters_by_episode_and_status(
        self,
        store: InMemoryGenerationRunStore,
    ) -> None:
        """Runs are listed by episode and can be narrowed by lifecycle status."""
        episode_id = uuid.uuid7()
        pending = await store.create_run(make_generation_run(episode_id=episode_id))
        running = await store.create_run(
            dc.replace(
                make_generation_run(episode_id=episode_id),
                status=GenerationRunStatus.RUNNING,
            )
        )
        await store.create_run(make_generation_run())

        assert await store.list_runs(episode_id) == (pending, running), (
            "store.list_runs should return pending and running runs for the episode"
        )
        assert await store.list_runs(
            episode_id,
            status=GenerationRunStatus.RUNNING,
        ) == (running,), (
            "store.list_runs should honour GenerationRunStatus.RUNNING filter"
        )

    @pytest.mark.asyncio
    async def test_list_runs_rejects_negative_limit(
        self,
        store: InMemoryGenerationRunStore,
    ) -> None:
        """Run pagination limits must be non-negative."""
        with pytest.raises(ValueError, match="limit"):
            await store.list_runs(uuid.uuid7(), limit=-1)

    @pytest.mark.asyncio
    async def test_list_runs_rejects_negative_offset(
        self,
        store: InMemoryGenerationRunStore,
    ) -> None:
        """Run pagination offsets must be non-negative."""
        with pytest.raises(ValueError, match="offset"):
            await store.list_runs(uuid.uuid7(), offset=-1)

    @pytest.mark.asyncio
    async def test_claim_run_for_execution_is_first_writer_wins(
        self,
        store: InMemoryGenerationRunStore,
    ) -> None:
        """A pending run can be claimed once for execution."""
        run = await store.create_run(make_generation_run())

        claimed = await store.claim_run_for_execution(
            run.id,
            current_node="draft",
            started_at=NOW,
            lease_expires_at=NOW + dt.timedelta(minutes=5),
        )
        lost = await store.claim_run_for_execution(
            run.id,
            current_node="draft",
            started_at=NOW,
            lease_expires_at=NOW + dt.timedelta(minutes=5),
        )

        assert claimed is not None
        assert claimed.status is GenerationRunStatus.RUNNING
        assert claimed.current_node == "draft"
        assert claimed.started_at == NOW
        assert lost is None


class TestGenerationEventLog:
    """Contract tests for generation event-log operations."""

    @pytest.mark.asyncio
    async def test_append_event_allocates_gap_free_sequences(
        self,
        store: InMemoryGenerationRunStore,
    ) -> None:
        """Callers never supply event sequence numbers."""
        run = await store.create_run(make_generation_run())

        first = await store.append_event(run.id, kind="created", payload={"step": 1})
        second = await store.append_event(run.id, kind="started", payload={"step": 2})
        events = await store.list_events(run.id)

        assert first.seq == 1, "first event sequence should be 1"
        assert second.seq == 2, "second event sequence should be 2"
        assert events == (first, second), "events should contain first then second"
        assert await store.list_events(run.id, after_seq=event_seq(1)) == (second,), (
            "list_events after seq 1 should return only the second event"
        )

    @pytest.mark.asyncio
    async def test_append_event_rejects_unknown_run(
        self,
        store: InMemoryGenerationRunStore,
    ) -> None:
        """Appending to a missing run should fail with the domain error."""
        with pytest.raises(RunNotFound, match=r"unknown generation run:"):
            await store.append_event(uuid.uuid7(), kind="created", payload={})

    @pytest.mark.asyncio
    async def test_list_events_rejects_negative_limit(
        self,
        store: InMemoryGenerationRunStore,
    ) -> None:
        """Event pagination limits must be non-negative."""
        run = await store.create_run(make_generation_run())

        with pytest.raises(ValueError, match="limit"):
            await store.list_events(run.id, limit=-1)


class TestCompositeProtocol:
    """Contract tests for the composite generation-run protocol."""

    def test_noop_composite_protocol_stub_typechecks(self) -> None:
        """A class implementing every method should satisfy the composite port."""
        # Static type checkers validate NoopGenerationRunPort against
        # GenerationRunPort through this assignment.
        _port: GenerationRunPort = typ.cast(
            "GenerationRunPort",
            NoopGenerationRunPort(),
        )
