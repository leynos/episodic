"""Generated lifecycle invariants for the in-process generation launcher."""

import datetime as dt
import typing as typ
import uuid

import hypothesis.strategies as st
import pytest
from hypothesis import given, settings

from episodic.canonical.domain import GenerationRun, GenerationRunStatus, SourceDocument
from episodic.canonical.storage import SqlAlchemyUnitOfWork
from episodic.generation.draft_script import (
    DraftScriptGenerator,
    DraftScriptTransientProviderError,
)
from tests.canonical_storage._generation_run_support import (
    make_generation_run,
    persist_generation_run_prerequisites,
)
from tests.generation_run_launcher_support import (
    BlockingDraftGenerator,
    FailingDraftGenerator,
    RecordingDraftGenerator,
    draft_result,
    launcher,
    valid_tei,
)

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


_session_factory: async_sessionmaker[AsyncSession] | None = None


@pytest.fixture(autouse=True)
def _configure_session_factory(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Make the isolated SQL test factory available to generated examples."""
    global _session_factory
    _session_factory = session_factory


def _current_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the function-scoped SQL factory configured for this test."""
    if _session_factory is None:
        msg = "Launcher property-test session factory was not configured."
        raise RuntimeError(msg)
    return _session_factory


async def _create_pending_run(
    factory: async_sessionmaker[AsyncSession],
) -> GenerationRun:
    """Persist one launchable run with its generated-lifecycle source."""
    run = make_generation_run()
    await persist_generation_run_prerequisites(factory, run)
    async with SqlAlchemyUnitOfWork(factory) as uow:
        await uow.generation_runs.create_run(run)
        await uow.source_documents.add(
            SourceDocument(
                id=uuid.uuid7(),
                ingestion_job_id=run.source_bundle_id,
                canonical_episode_id=run.episode_id,
                reference_document_revision_id=None,
                source_type="research_note",
                source_uri="https://example.test/source",
                weight=1.0,
                content_hash="sha256:source",
                metadata={"content": "generated lifecycle source"},
                created_at=dt.datetime(2026, 8, 20, tzinfo=dt.UTC),
            )
        )
        await uow.commit()
    return run


def _generator_for_outcome(outcome: str) -> DraftScriptGenerator:
    """Return the draft-generator double for one lifecycle outcome."""
    match outcome:
        case "success":
            return RecordingDraftGenerator(draft_result(valid_tei()))
        case "failure":
            return FailingDraftGenerator(DraftScriptTransientProviderError("retry"))
        case _:
            return BlockingDraftGenerator()


def _assert_terminal_event_kinds(event_kinds: tuple[str, ...]) -> None:
    """Assert that the lifecycle begins and ends with its expected events."""
    assert event_kinds[-1] in {"run.succeeded", "run.failed"}, event_kinds
    assert event_kinds[0] == "run.started", event_kinds


def _assert_outcome(run: GenerationRun, outcome: str) -> None:
    """Assert the persisted terminal state for one generated lifecycle."""
    match outcome:
        case "success":
            assert run.status is GenerationRunStatus.SUCCEEDED, (
                f"expected successful run {run.id}, got {run.status.value}"
            )
            assert run.error_category is None, run.error_category
        case "failure":
            assert run.status is GenerationRunStatus.FAILED, (
                f"expected failed run {run.id}, got {run.status.value}"
            )
            assert run.error_category == "provider.transient", run.error_category
        case _:
            assert run.status is GenerationRunStatus.FAILED, (
                f"expected cancelled run {run.id}, got {run.status.value}"
            )
            assert run.error_category == "launcher.shutdown", run.error_category


@given(outcome=st.sampled_from(("success", "failure", "cancelled")))
@settings(
    max_examples=3,
    deadline=None,
)
@pytest.mark.asyncio
async def test_launcher_generated_lifecycles_end_with_one_terminal_event(
    outcome: str,
) -> None:
    """Success, provider failure, and shutdown cancellation reach one terminal state."""
    factory = _current_session_factory()
    run = await _create_pending_run(factory)
    generator = _generator_for_outcome(outcome)
    run_launcher = launcher(factory, generator)

    await run_launcher.launch(run.id)
    match outcome:
        case "cancelled":
            await typ.cast("BlockingDraftGenerator", generator).started.wait()
            await run_launcher.shutdown()
        case _:
            await run_launcher.drain()

    async with SqlAlchemyUnitOfWork(factory) as uow:
        persisted_run = await uow.generation_runs.get_run(run.id)
        events = await uow.generation_runs.list_events(run.id)

    assert persisted_run is not None, f"expected persisted run {run.id}"
    assert persisted_run.status.is_terminal(), (
        f"expected terminal run {run.id}, got {persisted_run.status.value}"
    )
    _assert_terminal_event_kinds(tuple(event.kind for event in events))
    _assert_outcome(persisted_run, outcome)
