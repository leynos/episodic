"""Contract tests for generation checkpoint port implementations."""

import datetime as dt
import uuid

import pytest

from episodic.canonical.adapters.generation_runs import InMemoryGenerationRunStore
from episodic.canonical.domain import (
    CheckpointAction,
    CheckpointResponse,
    CheckpointStatus,
)
from episodic.canonical.generation_run_errors import CheckpointNotFound
from tests.test_generation_run_port_contract import (
    NOW,
    make_checkpoint,
    make_generation_run,
)


@pytest.fixture
def store() -> InMemoryGenerationRunStore:
    """Create a deterministic in-memory store for each contract test."""
    return InMemoryGenerationRunStore(time_provider=lambda: NOW)


class TestGenerationCheckpointPort:
    """Contract tests for generation checkpoint operations."""

    @pytest.mark.asyncio
    async def test_checkpoint_response_uses_domain_transition(
        self,
        store: InMemoryGenerationRunStore,
    ) -> None:
        """The checkpoint port persists the response returned by the entity."""
        run = await store.create_run(make_generation_run())
        checkpoint = await store.create_checkpoint(make_checkpoint(run.id))

        responded = await store.respond_to_checkpoint(
            checkpoint.id,
            response=CheckpointResponse(
                action=CheckpointAction.APPROVE,
                payload={"approved": True},
                responded_at=NOW + dt.timedelta(minutes=1),
                responded_by="reviewer@example.com",
            ),
        )

        assert responded.status is CheckpointStatus.RESPONDED, (
            "checkpoint status must transition to RESPONDED"
        )
        assert responded.response_payload == {"approved": True}, (
            "response payload must be persisted"
        )
        assert await store.get_checkpoint(checkpoint.id) == responded, (
            "retrieved checkpoint must reflect response"
        )

    @pytest.mark.asyncio
    async def test_checkpoint_timeout_uses_domain_transition(
        self,
        store: InMemoryGenerationRunStore,
    ) -> None:
        """The checkpoint port persists the timeout returned by the entity."""
        run = await store.create_run(make_generation_run())
        checkpoint = await store.create_checkpoint(make_checkpoint(run.id))

        timed_out = await store.time_out_checkpoint(
            checkpoint.id,
            at=NOW + dt.timedelta(minutes=30),
        )

        assert timed_out.status is CheckpointStatus.TIMED_OUT, (
            "checkpoint status must transition to TIMED_OUT"
        )
        assert timed_out.responded_at == NOW + dt.timedelta(minutes=30), (
            "timeout timestamp must be persisted"
        )
        assert await store.get_checkpoint(checkpoint.id) == timed_out, (
            "retrieved checkpoint must reflect timeout"
        )

    @pytest.mark.asyncio
    async def test_checkpoint_cancellation_uses_domain_transition(
        self,
        store: InMemoryGenerationRunStore,
    ) -> None:
        """The checkpoint port persists cancellation returned by the entity."""
        run = await store.create_run(make_generation_run())
        checkpoint = await store.create_checkpoint(make_checkpoint(run.id))

        cancelled = await store.cancel_checkpoint(
            checkpoint.id,
            at=NOW + dt.timedelta(minutes=10),
        )

        assert cancelled.status is CheckpointStatus.CANCELLED, (
            "checkpoint status must transition to CANCELLED"
        )
        assert cancelled.responded_at == NOW + dt.timedelta(minutes=10), (
            "cancellation timestamp must be persisted"
        )
        assert await store.get_checkpoint(checkpoint.id) == cancelled, (
            "retrieved checkpoint must reflect cancellation"
        )

    @pytest.mark.asyncio
    async def test_checkpoint_response_rejects_unknown_checkpoint(
        self,
        store: InMemoryGenerationRunStore,
    ) -> None:
        """Responding to a missing checkpoint should raise the domain error."""
        with pytest.raises(CheckpointNotFound, match=r"unknown generation checkpoint:"):
            await store.respond_to_checkpoint(
                uuid.uuid7(),
                response=CheckpointResponse(
                    action=CheckpointAction.APPROVE,
                    payload={},
                    responded_at=NOW,
                    responded_by="reviewer@example.com",
                ),
            )
