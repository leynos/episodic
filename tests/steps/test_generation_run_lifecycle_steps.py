"""Behavioural steps for generation-run checkpoint lifecycles."""

from __future__ import annotations

import contextlib
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
from episodic.canonical.generation_quality import QaStatus, QualityMode
from episodic.canonical.generation_run_errors import CheckpointAlreadyTerminal
from episodic.canonical.storage import SqlAlchemyUnitOfWork
from tests.canonical_storage._generation_run_support import (
    persist_generation_run_prerequisites,
)

if typ.TYPE_CHECKING:
    import asyncio
    import collections.abc as cabc

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from episodic.canonical.generation_run_ports import GenerationRunPort

NOW = dt.datetime(2026, 6, 4, 8, 0, tzinfo=dt.UTC)
_ACTION_PAYLOADS: dict[str, dict[str, object]] = {
    "approve": {"approved": True},
    "request_changes": {"approved": False},
    "edit": {"approved": False},
}


# The durability scenario holds one unit of work open across three steps, so the
# session cannot be owned by a `with` block inside a single step. The runner
# supplies the event loop in that case: a session is bound to the loop that
# created it, so every step in a scenario must share one loop.
@dc.dataclass(slots=True)
class GenerationRunLifecycleContext:
    """Shared state for checkpoint lifecycle scenarios."""

    runner: asyncio.Runner
    session_factory: async_sessionmaker[AsyncSession] | None = None
    store: GenerationRunPort = dc.field(default_factory=InMemoryGenerationRunStore)
    uow: SqlAlchemyUnitOfWork | None = None
    stack: contextlib.AsyncExitStack | None = None
    run: GenerationRun | None = None
    checkpoint: Checkpoint | None = None
    reloaded: Checkpoint | None = None
    error: Exception | None = None

    def tear_down(self) -> None:
        """Release a unit of work the scenario left open."""
        self.runner.run(_close(self))


async def _close(ctx: GenerationRunLifecycleContext) -> None:
    """Close a scenario's exit stack, releasing its unit of work."""
    stack = ctx.stack
    ctx.stack = None
    if stack is not None:
        await stack.aclose()


@pytest.fixture
def generation_run_context(
    _function_scoped_runner: asyncio.Runner,
    session_factory: async_sessionmaker[AsyncSession],
) -> cabc.Iterator[GenerationRunLifecycleContext]:
    """Create isolated BDD state for each scenario."""
    ctx = GenerationRunLifecycleContext(
        runner=_function_scoped_runner,
        session_factory=session_factory,
    )
    yield ctx
    ctx.tear_down()


def _require[T](value: T | None, message: str) -> T:
    """Return a required context value, failing the scenario when absent."""
    if value is None:
        raise AssertionError(message)
    return value


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
        quality_mode=QualityMode.DRAFT_WITHOUT_QA,
        qa_status=QaStatus.SKIPPED,
        skip_qa_rationale="No-QA vertical-slice draft.",
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


def _response(action: str, *, offset_minutes: int) -> CheckpointResponse:
    """Build a reviewer response for the named action."""
    return CheckpointResponse(
        action=CheckpointAction(action),
        payload=_ACTION_PAYLOADS[action],
        responded_at=NOW + dt.timedelta(minutes=offset_minutes),
        responded_by="reviewer@example.com",
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


@scenario(
    "../features/generation_run_lifecycle.feature",
    "A responded checkpoint survives a new unit of work",
)
def test_responded_checkpoint_survives_new_unit_of_work() -> None:
    """Run the durability scenario."""


@given("a generation run with a created checkpoint")
def created_checkpoint(
    generation_run_context: GenerationRunLifecycleContext,
) -> None:
    """Create a generation run checkpoint awaiting review."""
    ctx = generation_run_context
    run = ctx.runner.run(ctx.store.create_run(_run()))
    ctx.checkpoint = ctx.runner.run(ctx.store.create_checkpoint(_checkpoint(run.id)))


@given("a checkpoint that has already been responded to")
def responded_checkpoint(
    generation_run_context: GenerationRunLifecycleContext,
) -> None:
    """Create a checkpoint that already reached a terminal response state."""
    ctx = generation_run_context
    run = ctx.runner.run(ctx.store.create_run(_run()))
    checkpoint = ctx.runner.run(ctx.store.create_checkpoint(_checkpoint(run.id)))
    ctx.checkpoint = ctx.runner.run(
        ctx.store.respond_to_checkpoint(
            checkpoint.id,
            response=_response("approve", offset_minutes=1),
        )
    )


@given("a generation run persisted in PostgreSQL")
def run_persisted_in_postgres(
    generation_run_context: GenerationRunLifecycleContext,
) -> None:
    """Open a unit of work over a run whose foreign keys are committed."""
    ctx = generation_run_context

    async def prepare() -> GenerationRun:
        factory = _require(ctx.session_factory, "Scenario needs a session factory.")
        run = _run()
        await persist_generation_run_prerequisites(factory, run)
        stack = contextlib.AsyncExitStack()
        uow = await stack.enter_async_context(SqlAlchemyUnitOfWork(factory))
        ctx.stack = stack
        ctx.uow = uow
        ctx.store = uow.generation_runs
        await uow.generation_runs.create_run(run)
        return run

    ctx.run = ctx.runner.run(prepare())


@given("a checkpoint created against that run")
def checkpoint_created_against_run(
    generation_run_context: GenerationRunLifecycleContext,
) -> None:
    """Create the checkpoint the durability scenario responds to."""
    ctx = generation_run_context
    run = _require(ctx.run, "Generation run was not prepared.")
    ctx.checkpoint = ctx.runner.run(ctx.store.create_checkpoint(_checkpoint(run.id)))


@when(parsers.parse('the reviewer responds with action "{action}"'))
def reviewer_responds(
    generation_run_context: GenerationRunLifecycleContext,
    action: str,
) -> None:
    """Respond to the active checkpoint."""
    ctx = generation_run_context
    checkpoint = _require(ctx.checkpoint, "Checkpoint was not prepared.")
    ctx.checkpoint = ctx.runner.run(
        ctx.store.respond_to_checkpoint(
            checkpoint.id,
            response=_response(action, offset_minutes=1),
        )
    )


@when("the reviewer attempts to respond again")
def reviewer_attempts_second_response(
    generation_run_context: GenerationRunLifecycleContext,
) -> None:
    """Try to respond to a terminal checkpoint."""
    ctx = generation_run_context
    checkpoint = _require(ctx.checkpoint, "Checkpoint was not prepared.")
    try:
        ctx.runner.run(
            ctx.store.respond_to_checkpoint(
                checkpoint.id,
                response=_response("edit", offset_minutes=2),
            )
        )
    except Exception as exc:  # ruff: ignore[blind-except] - BDD step captures the outcome.
        ctx.error = exc


def _apply_terminal_transition(
    ctx: GenerationRunLifecycleContext,
    coro: cabc.Awaitable[Checkpoint],
) -> None:
    """Run a terminal-transition coroutine and store the resulting checkpoint."""

    async def await_transition() -> Checkpoint:
        return await coro

    ctx.checkpoint = ctx.runner.run(await_transition())


@when("the checkpoint times out")
def checkpoint_times_out(
    generation_run_context: GenerationRunLifecycleContext,
) -> None:
    """Move the checkpoint to the timeout terminal state."""
    ctx = generation_run_context
    _apply_terminal_transition(
        ctx,
        ctx.store.time_out_checkpoint(
            _require(ctx.checkpoint, "Checkpoint was not prepared.").id,
            at=NOW + dt.timedelta(hours=1),
        ),
    )


@when("the checkpoint is cancelled")
def checkpoint_is_cancelled(
    generation_run_context: GenerationRunLifecycleContext,
) -> None:
    """Move the checkpoint to the cancelled terminal state."""
    ctx = generation_run_context
    _apply_terminal_transition(
        ctx,
        ctx.store.cancel_checkpoint(
            _require(ctx.checkpoint, "Checkpoint was not prepared.").id,
            at=NOW + dt.timedelta(minutes=10),
        ),
    )


@when("the unit of work is committed and closed")
def unit_of_work_committed_and_closed(
    generation_run_context: GenerationRunLifecycleContext,
) -> None:
    """Commit the scenario's unit of work and release its session."""
    ctx = generation_run_context
    ctx.runner.run(_commit_and_close(ctx))


@then(parsers.parse('the checkpoint status becomes "{status}"'))
def checkpoint_status_becomes(
    generation_run_context: GenerationRunLifecycleContext,
    status: str,
) -> None:
    """Assert the final checkpoint status."""
    ctx = generation_run_context
    checkpoint = _require(ctx.checkpoint, "Checkpoint was not prepared.")
    assert checkpoint.status is CheckpointStatus(status), "Expected values to match"


@then("the response payload is recorded")
def response_payload_recorded(
    generation_run_context: GenerationRunLifecycleContext,
) -> None:
    """Assert the reviewer response payload was persisted on the entity."""
    ctx = generation_run_context
    checkpoint = _require(ctx.checkpoint, "Checkpoint was not prepared.")
    assert checkpoint.response_payload == {"approved": True}, "Expected values to match"


@then("a CheckpointAlreadyTerminal error is raised")
def checkpoint_already_terminal_error_raised(
    generation_run_context: GenerationRunLifecycleContext,
) -> None:
    """Assert the double response failed with the domain error."""
    assert isinstance(
        generation_run_context.error,
        CheckpointAlreadyTerminal,
    ), f"Expected CheckpointAlreadyTerminal, got {generation_run_context.error!r}."


async def _commit_and_close(ctx: GenerationRunLifecycleContext) -> None:
    """Commit the scenario's unit of work, then release its stack."""
    await _require(ctx.uow, "No unit of work is open.").commit()
    await _close(ctx)


async def _read_fresh(
    ctx: GenerationRunLifecycleContext,
    checkpoint_id: uuid.UUID,
) -> Checkpoint | None:
    """Read a checkpoint back through a brand-new unit of work."""
    factory = _require(ctx.session_factory, "Scenario needs a session factory.")
    async with SqlAlchemyUnitOfWork(factory) as uow:
        return await uow.generation_runs.get_checkpoint(checkpoint_id)


@then(
    parsers.parse(
        'reading the checkpoint in a new unit of work reports status "{status}"'
    )
)
def checkpoint_status_read_fresh(
    generation_run_context: GenerationRunLifecycleContext,
    status: str,
) -> None:
    """Assert a later unit of work observes the committed status."""
    ctx = generation_run_context
    checkpoint = _require(ctx.checkpoint, "Checkpoint was not prepared.")
    ctx.reloaded = ctx.runner.run(_read_fresh(ctx, checkpoint.id))
    reloaded = _require(ctx.reloaded, "Checkpoint was not re-read.")
    assert reloaded.status is CheckpointStatus(status), "Expected values to match"


@then(parsers.parse('the recorded reviewer action is "{action}"'))
def recorded_reviewer_action(
    generation_run_context: GenerationRunLifecycleContext,
    action: str,
) -> None:
    """Assert the reviewer action survived the commit."""
    ctx = generation_run_context
    reloaded = _require(ctx.reloaded, "Checkpoint was not re-read.")
    assert reloaded.response_action is CheckpointAction(action), (
        "Expected values to match"
    )
