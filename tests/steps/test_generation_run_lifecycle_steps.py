"""Behavioural steps for generation-run checkpoint lifecycles."""

from __future__ import annotations

import asyncio
import dataclasses as dc
import datetime as dt
import typing as typ
import uuid

import pytest
from pytest_bdd import given, parsers, scenario, then, when

from episodic.canonical.adapters.generation_runs import InMemoryGenerationRunStore
from episodic.canonical.domain import (
    Checkpoint,
    CheckpointAction,
    CheckpointResponse,
    CheckpointStatus,
    GenerationRun,
    GenerationRunStatus,
)
from episodic.canonical.generation_run_errors import CheckpointAlreadyTerminal

if typ.TYPE_CHECKING:
    import collections.abc as cabc

NOW = dt.datetime(2026, 6, 4, 8, 0, tzinfo=dt.UTC)
_ACTION_PAYLOADS: dict[str, dict[str, object]] = {
    "approve": {"approved": True},
    "request_changes": {"approved": False},
    "edit": {"approved": False},
}


@dc.dataclass(slots=True)
class GenerationRunLifecycleContext:
    """Shared state for checkpoint lifecycle scenarios."""

    store: InMemoryGenerationRunStore = dc.field(
        default_factory=InMemoryGenerationRunStore
    )
    checkpoint: Checkpoint | None = None
    error: Exception | None = None


@pytest.fixture
def generation_run_context() -> GenerationRunLifecycleContext:
    """Create isolated BDD state for each scenario."""
    return GenerationRunLifecycleContext()


def _run() -> GenerationRun:
    """Return a sample generation run for tests."""
    return GenerationRun(
        id=uuid.uuid7(),
        episode_id=uuid.uuid7(),
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
    )


def _checkpoint(run_id: uuid.UUID) -> Checkpoint:
    """Return a sample checkpoint for tests."""
    return Checkpoint(
        id=uuid.uuid7(),
        generation_run_id=run_id,
        node="human_review",
        prompt="Approve the draft?",
        options=("approve", "request_changes", "edit"),
        status=CheckpointStatus.CREATED,
        created_at=NOW,
        responded_at=None,
        responded_by=None,
        response_action=None,
        response_payload={},
    )


@scenario(
    "../features/generation_run_lifecycle.feature", "Reviewer approves a checkpoint"
)
def test_reviewer_approves_checkpoint() -> None:
    """Run the approve-checkpoint scenario."""


@scenario(
    "../features/generation_run_lifecycle.feature", "Reviewer cannot respond twice"
)
def test_reviewer_cannot_respond_twice() -> None:
    """Run the double-response scenario."""


@scenario("../features/generation_run_lifecycle.feature", "A checkpoint times out")
def test_checkpoint_times_out() -> None:
    """Run the timeout scenario."""


@scenario("../features/generation_run_lifecycle.feature", "A checkpoint is cancelled")
def test_checkpoint_is_cancelled() -> None:
    """Run the cancellation scenario."""


@given("a generation run with a created checkpoint")
def created_checkpoint(
    generation_run_context: GenerationRunLifecycleContext,
) -> None:
    """Create a generation run checkpoint awaiting review."""
    run = asyncio.run(generation_run_context.store.create_run(_run()))
    generation_run_context.checkpoint = asyncio.run(
        generation_run_context.store.create_checkpoint(_checkpoint(run.id))
    )


@given("a checkpoint that has already been responded to")
def responded_checkpoint(
    generation_run_context: GenerationRunLifecycleContext,
) -> None:
    """Create a checkpoint that already reached a terminal response state."""
    run = asyncio.run(generation_run_context.store.create_run(_run()))
    checkpoint = asyncio.run(
        generation_run_context.store.create_checkpoint(_checkpoint(run.id))
    )
    generation_run_context.checkpoint = asyncio.run(
        generation_run_context.store.respond_to_checkpoint(
            checkpoint.id,
            response=CheckpointResponse(
                action=CheckpointAction.APPROVE,
                payload={"approved": True},
                responded_at=NOW + dt.timedelta(minutes=1),
                responded_by="reviewer@example.com",
            ),
        )
    )


@when(parsers.parse('the reviewer responds with action "{action}"'))
def reviewer_responds(
    generation_run_context: GenerationRunLifecycleContext,
    action: str,
) -> None:
    """Respond to the active checkpoint."""
    checkpoint = generation_run_context.checkpoint
    if checkpoint is None:
        msg = "Checkpoint was not prepared."
        raise AssertionError(msg)
    generation_run_context.checkpoint = asyncio.run(
        generation_run_context.store.respond_to_checkpoint(
            checkpoint.id,
            response=CheckpointResponse(
                action=CheckpointAction(action),
                payload=_ACTION_PAYLOADS[action],
                responded_at=NOW + dt.timedelta(minutes=1),
                responded_by="reviewer@example.com",
            ),
        )
    )


@when("the reviewer attempts to respond again")
def reviewer_attempts_second_response(
    generation_run_context: GenerationRunLifecycleContext,
) -> None:
    """Try to respond to a terminal checkpoint."""
    checkpoint = generation_run_context.checkpoint
    if checkpoint is None:
        msg = "Checkpoint was not prepared."
        raise AssertionError(msg)
    try:
        asyncio.run(
            generation_run_context.store.respond_to_checkpoint(
                checkpoint.id,
                response=CheckpointResponse(
                    action=CheckpointAction.EDIT,
                    payload={},
                    responded_at=NOW + dt.timedelta(minutes=2),
                    responded_by="reviewer@example.com",
                ),
            )
        )
    except Exception as exc:  # noqa: BLE001 - BDD step captures the outcome.
        generation_run_context.error = exc


def _require_checkpoint(
    ctx: GenerationRunLifecycleContext,
) -> Checkpoint:
    """Return the context checkpoint, raising AssertionError if absent."""
    checkpoint = ctx.checkpoint
    if checkpoint is None:
        msg = "Checkpoint was not prepared."
        raise AssertionError(msg)
    return checkpoint


def _apply_terminal_transition(
    ctx: GenerationRunLifecycleContext,
    coro: cabc.Awaitable[Checkpoint],
) -> None:
    """Run a terminal-transition coroutine and store the resulting checkpoint."""

    async def await_transition() -> Checkpoint:
        return await coro

    ctx.checkpoint = asyncio.run(await_transition())


@when("the checkpoint times out")
def checkpoint_times_out(
    generation_run_context: GenerationRunLifecycleContext,
) -> None:
    """Move the checkpoint to the timeout terminal state."""
    _apply_terminal_transition(
        generation_run_context,
        generation_run_context.store.time_out_checkpoint(
            _require_checkpoint(generation_run_context).id,
            at=NOW + dt.timedelta(hours=1),
        ),
    )


@when("the checkpoint is cancelled")
def checkpoint_is_cancelled(
    generation_run_context: GenerationRunLifecycleContext,
) -> None:
    """Move the checkpoint to the cancelled terminal state."""
    _apply_terminal_transition(
        generation_run_context,
        generation_run_context.store.cancel_checkpoint(
            _require_checkpoint(generation_run_context).id,
            at=NOW + dt.timedelta(minutes=10),
        ),
    )


@then(parsers.parse('the checkpoint status becomes "{status}"'))
def checkpoint_status_becomes(
    generation_run_context: GenerationRunLifecycleContext,
    status: str,
) -> None:
    """Assert the final checkpoint status."""
    assert _require_checkpoint(generation_run_context).status is CheckpointStatus(
        status
    )


@then("the response payload is recorded")
def response_payload_recorded(
    generation_run_context: GenerationRunLifecycleContext,
) -> None:
    """Assert the reviewer response payload was persisted on the entity."""
    checkpoint = generation_run_context.checkpoint
    if checkpoint is None:
        msg = "Checkpoint was not prepared."
        raise AssertionError(msg)
    assert checkpoint.response_payload == {"approved": True}


@then("a CheckpointAlreadyTerminal error is raised")
def checkpoint_already_terminal_error_raised(
    generation_run_context: GenerationRunLifecycleContext,
) -> None:
    """Assert the double response failed with the domain error."""
    assert isinstance(
        generation_run_context.error,
        CheckpointAlreadyTerminal,
    ), f"Expected CheckpointAlreadyTerminal, got {generation_run_context.error!r}."
