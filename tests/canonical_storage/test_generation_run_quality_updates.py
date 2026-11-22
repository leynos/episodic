"""SQL witness table for QA-quality status updates (INV-2).

The existing SQL property contract runs too few examples to cover every
accept/reject class, so this module pins a literal table against py-pglite.
A rejected update must leave the persisted row unchanged.
"""

import dataclasses as dc
import typing as typ
import uuid

import pytest

from episodic.canonical.domain import GenerationRun, GenerationRunStatus
from episodic.canonical.generation_quality import QaStatus, QualityMode
from episodic.canonical.generation_run_errors import RunAlreadyTerminal
from episodic.canonical.generation_run_ports import (
    UNCHANGED,
    GenerationRunStatusUpdate,
)
from episodic.canonical.storage import SqlAlchemyUnitOfWork
from tests.canonical_storage._generation_run_support import (
    NOW,
    GenerationRunFixture,
    make_generation_run,
    persist_generation_run_prerequisites,
)

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _gated_run(
    *,
    status: GenerationRunStatus = GenerationRunStatus.RUNNING,
    qa_status: QaStatus = QaStatus.PENDING,
) -> GenerationRun:
    """Build a QA-gated run in the requested lifecycle state."""
    return dc.replace(
        make_generation_run(GenerationRunFixture(run_id=uuid.uuid7())),
        quality_mode=QualityMode.QA_GATED,
        qa_status=qa_status,
        skip_qa_rationale=None,
        status=status,
        ended_at=NOW if status.is_terminal() else None,
    )


def _no_qa_run() -> GenerationRun:
    """Build a running no-QA run."""
    return dc.replace(
        make_generation_run(GenerationRunFixture(run_id=uuid.uuid7())),
        status=GenerationRunStatus.RUNNING,
    )


async def _apply_update(
    factory: async_sessionmaker[AsyncSession],
    run_id: uuid.UUID,
    update: GenerationRunStatusUpdate,
) -> None:
    """Apply one update in its own unit of work and commit."""
    async with SqlAlchemyUnitOfWork(factory) as uow:
        await uow.generation_runs.update_run_status(run_id, update=update)
        await uow.commit()


async def _reload(
    factory: async_sessionmaker[AsyncSession],
    run_id: uuid.UUID,
) -> GenerationRun:
    """Read a run back through a fresh unit of work."""
    async with SqlAlchemyUnitOfWork(factory) as uow:
        run = await uow.generation_runs.get_run(run_id)
    assert run is not None, f"run {run_id} disappeared"
    return run


def _success_update(
    qa_status: QaStatus | object = UNCHANGED,
) -> GenerationRunStatusUpdate:
    """Build a succeeded terminal update with an optional QA status."""
    return GenerationRunStatusUpdate(
        status=GenerationRunStatus.SUCCEEDED,
        current_node=None,
        ended_at=NOW,
        qa_status=typ.cast("QaStatus", qa_status),
    )


def _failure_update(
    qa_status: QaStatus | object = UNCHANGED,
) -> GenerationRunStatusUpdate:
    """Build a failed terminal update with an optional QA status."""
    return GenerationRunStatusUpdate(
        status=GenerationRunStatus.FAILED,
        current_node=None,
        ended_at=NOW,
        error_message="QA escalated the draft.",
        error_category="qa.escalation_required",
        qa_status=typ.cast("QaStatus", qa_status),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("run_factory", "update", "expected"),
    [
        pytest.param(
            _gated_run,
            _success_update(QaStatus.PASSED),
            (GenerationRunStatus.SUCCEEDED, QaStatus.PASSED),
            id="gated-pass",
        ),
        pytest.param(
            _gated_run,
            _failure_update(QaStatus.FAILED),
            (GenerationRunStatus.FAILED, QaStatus.FAILED),
            id="gated-fail",
        ),
        pytest.param(
            _gated_run,
            _failure_update(),
            (GenerationRunStatus.FAILED, QaStatus.PENDING),
            id="gated-fail-keeps-pending",
        ),
        pytest.param(
            _no_qa_run,
            _success_update(),
            (GenerationRunStatus.SUCCEEDED, QaStatus.SKIPPED),
            id="no-qa-success",
        ),
    ],
)
async def test_accepted_updates_persist_the_resolved_state(
    session_factory: async_sessionmaker[AsyncSession],
    run_factory: cabc.Callable[[], GenerationRun],
    update: GenerationRunStatusUpdate,
    expected: tuple[GenerationRunStatus, QaStatus],
) -> None:
    """Accepted updates persist the resolved status and preserved QA status."""
    expected_status, expected_qa = expected
    run = run_factory()
    await persist_generation_run_prerequisites(session_factory, run)
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        await uow.generation_runs.create_run(run)
        await uow.commit()
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        updated = await uow.generation_runs.update_run_status(run.id, update=update)
        await uow.commit()

    reloaded = await _reload(session_factory, run.id)
    assert updated.status is expected_status, f"update result status={updated.status!r}"
    assert reloaded.status is expected_status, f"persisted status {reloaded.status}"
    assert reloaded.qa_status is expected_qa, (
        f"persisted qa_status {reloaded.qa_status}"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("update", "match"),
    [
        pytest.param(_success_update(), "qa_status", id="gated-success-without-pass"),
        pytest.param(
            _success_update(QaStatus.PENDING), "qa_status", id="gated-pending-success"
        ),
        pytest.param(
            _failure_update(QaStatus.PASSED), "passed", id="gated-pass-then-fail"
        ),
    ],
)
async def test_rejected_updates_leave_the_row_unchanged(
    session_factory: async_sessionmaker[AsyncSession],
    update: GenerationRunStatusUpdate,
    match: str,
) -> None:
    """A rejected update rolls back and preserves the original row."""
    run = _gated_run()
    await persist_generation_run_prerequisites(session_factory, run)
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        await uow.generation_runs.create_run(run)
        await uow.commit()

    with pytest.raises(ValueError, match=match):
        await _apply_update(session_factory, run.id, update)

    reloaded = await _reload(session_factory, run.id)
    assert reloaded.status is GenerationRunStatus.RUNNING, (
        f"rejected update changed status to {reloaded.status}"
    )
    assert reloaded.qa_status is QaStatus.PENDING, (
        f"rejected update changed qa_status to {reloaded.qa_status}"
    )


@pytest.mark.asyncio
async def test_late_failure_after_a_persisted_pass_is_refused(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A terminal run cannot later record a failure that contradicts its pass."""
    run = _gated_run()
    await persist_generation_run_prerequisites(session_factory, run)
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        await uow.generation_runs.create_run(run)
        await uow.commit()
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        await uow.generation_runs.update_run_status(
            run.id,
            update=_success_update(QaStatus.PASSED),
        )
        await uow.commit()

    with pytest.raises(RunAlreadyTerminal):
        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            await uow.generation_runs.update_run_status(
                run.id, update=_failure_update()
            )

    reloaded = await _reload(session_factory, run.id)
    assert reloaded.status is GenerationRunStatus.SUCCEEDED, (
        f"persisted status={reloaded.status!r}"
    )
    assert reloaded.qa_status is QaStatus.PASSED, (
        f"persisted qa_status={reloaded.qa_status!r}"
    )
