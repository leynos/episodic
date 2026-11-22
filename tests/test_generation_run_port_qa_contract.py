"""QA-status rows for the in-memory generation-run port contract (INV-2).

The base contract module keeps the lifecycle cases; these rows pin the
QA-status sentinel and the "succeeded if and only if passed" rule.
"""

import dataclasses as dc
import datetime as dt
import typing as typ

import hypothesis.strategies as st
import pytest
from hypothesis import HealthCheck, example, given, settings

from episodic.canonical.adapters.generation_runs import InMemoryGenerationRunStore
from episodic.canonical.domain import (
    GenerationRun,
    GenerationRunStatus,
    apply_status_update,
)
from episodic.canonical.generation_quality import QaStatus, QualityMode
from episodic.canonical.generation_run_ports import (
    UNCHANGED,
    GenerationRunStatusUpdate,
)
from tests.test_generation_run_port_contract import make_generation_run

if typ.TYPE_CHECKING:
    import uuid

NOW = dt.datetime(2026, 6, 4, 8, 0, tzinfo=dt.UTC)


@pytest.fixture
def store() -> InMemoryGenerationRunStore:
    """Create a deterministic in-memory store for each contract test."""
    return InMemoryGenerationRunStore(time_provider=lambda: NOW)


async def _gated_running_run(
    store: InMemoryGenerationRunStore,
) -> GenerationRun:
    """Create a running QA-gated run in the pending QA state."""
    return await store.create_run(
        dc.replace(
            make_generation_run(),
            status=GenerationRunStatus.RUNNING,
            quality_mode=QualityMode.QA_GATED,
            qa_status=QaStatus.PENDING,
            skip_qa_rationale=None,
        )
    )


@pytest.mark.asyncio
async def test_update_run_status_applies_qa_status(
    store: InMemoryGenerationRunStore,
) -> None:
    """An explicit QA status is stored and an omitted one is preserved."""
    gated = await _gated_running_run(store)

    passed = await store.update_run_status(
        gated.id,
        update=GenerationRunStatusUpdate(
            status=GenerationRunStatus.SUCCEEDED,
            current_node=None,
            ended_at=NOW,
            qa_status=QaStatus.PASSED,
        ),
    )

    assert passed.qa_status is QaStatus.PASSED, (
        f"expected passed, got {passed.qa_status!r}"
    )
    assert await store.get_run(gated.id) == passed, "the update must persist"


def _policy_allows(
    mode: QualityMode,
    status: GenerationRunStatus,
    qa_status: QaStatus,
) -> bool:
    """State the QA-status rule for a resolved status and QA status."""
    if mode is QualityMode.DRAFT_WITHOUT_QA:
        return qa_status is QaStatus.SKIPPED
    return qa_status is not QaStatus.SKIPPED and (qa_status is QaStatus.PASSED) == (
        status is GenerationRunStatus.SUCCEEDED
    )


class _QualityStore(typ.Protocol):
    """The store operations the INV-2 property exercises."""

    async def create_run(self, run: GenerationRun) -> GenerationRun:
        """Persist a run."""
        ...

    async def get_run(self, run_id: uuid.UUID) -> GenerationRun | None:
        """Load a run."""
        ...

    async def update_run_status(
        self,
        run_id: uuid.UUID,
        *,
        update: GenerationRunStatusUpdate,
    ) -> GenerationRun:
        """Apply a status update."""
        ...


async def check_quality_update(
    store: _QualityStore,
    mode: QualityMode,
    update_status: GenerationRunStatus,
    update_qa: QaStatus | object,
) -> None:
    """Assert the accept/reject decision and effect for one update cell.

    The rejection branch is asserted through the property rather than beside
    it: a store that skips revalidation must make this checker fail.
    """
    no_qa = mode is QualityMode.DRAFT_WITHOUT_QA
    run = await store.create_run(
        dc.replace(
            make_generation_run(),
            status=GenerationRunStatus.RUNNING,
            quality_mode=mode,
            qa_status=QaStatus.SKIPPED if no_qa else QaStatus.PENDING,
            skip_qa_rationale="No-QA draft." if no_qa else None,
        )
    )
    update = GenerationRunStatusUpdate(
        status=update_status,
        current_node=None if update_status.is_terminal() else "evaluate",
        ended_at=NOW if update_status.is_terminal() else None,
        qa_status=typ.cast("QaStatus", update_qa),
    )
    resolved_qa = typ.cast(
        "QaStatus",
        run.qa_status if update_qa is UNCHANGED else update_qa,
    )
    if not _policy_allows(mode, update_status, resolved_qa):
        with pytest.raises(ValueError, match="qa_status"):
            await store.update_run_status(run.id, update=update)
        assert await store.get_run(run.id) == run, (
            "a rejected update must leave the row unchanged"
        )
        return

    updated = await store.update_run_status(run.id, update=update)
    assert updated.qa_status is resolved_qa, (
        f"resolved qa_status={updated.qa_status!r}, expected {resolved_qa!r}"
    )
    assert updated.status is update_status, updated.status
    assert await store.get_run(run.id) == updated, "the accepted update must persist"


@pytest.mark.asyncio
@example(
    mode=QualityMode.QA_GATED,
    update_status=GenerationRunStatus.SUCCEEDED,
    update_qa=QaStatus.PASSED,
)
@example(
    mode=QualityMode.QA_GATED,
    update_status=GenerationRunStatus.SUCCEEDED,
    update_qa=UNCHANGED,
)
@example(
    mode=QualityMode.QA_GATED,
    update_status=GenerationRunStatus.FAILED,
    update_qa=QaStatus.FAILED,
)
@example(
    mode=QualityMode.QA_GATED,
    update_status=GenerationRunStatus.RUNNING,
    update_qa=QaStatus.PASSED,
)
@example(
    mode=QualityMode.DRAFT_WITHOUT_QA,
    update_status=GenerationRunStatus.SUCCEEDED,
    update_qa=UNCHANGED,
)
@example(
    mode=QualityMode.DRAFT_WITHOUT_QA,
    update_status=GenerationRunStatus.SUCCEEDED,
    update_qa=QaStatus.PENDING,
)
@given(
    mode=st.sampled_from(tuple(QualityMode)),
    update_status=st.sampled_from(tuple(GenerationRunStatus)),
    update_qa=st.sampled_from([UNCHANGED, *tuple(QaStatus)]),
)
@settings(
    deadline=None,
    max_examples=60,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
async def test_quality_update_property(
    store: InMemoryGenerationRunStore,
    mode: QualityMode,
    update_status: GenerationRunStatus,
    update_qa: QaStatus | object,
) -> None:
    """Every update is accepted exactly when the mode's QA rule allows it."""
    await check_quality_update(store, mode, update_status, update_qa)


class _PolicyFreeStore:
    """Store double that applies updates without revalidating the policy."""

    def __init__(self, inner: InMemoryGenerationRunStore) -> None:
        """Wrap the store whose policy is removed."""
        self._inner = inner
        self._overrides: dict[uuid.UUID, GenerationRun] = {}

    async def create_run(self, run: GenerationRun) -> GenerationRun:
        """Persist a run through the wrapped store."""
        return await self._inner.create_run(run)

    async def get_run(self, run_id: uuid.UUID) -> GenerationRun | None:
        """Return the policy-free mutation when one exists."""
        return self._overrides.get(run_id, await self._inner.get_run(run_id))

    async def update_run_status(
        self,
        run_id: uuid.UUID,
        *,
        update: GenerationRunStatusUpdate,
    ) -> GenerationRun:
        """Apply the update by mutating fields directly, bypassing validation."""
        run = await self._inner.get_run(run_id)
        assert run is not None, f"run {run_id} is missing"
        mutated = dc.replace(run)
        object.__setattr__(mutated, "status", update.status)
        object.__setattr__(mutated, "current_node", update.current_node)
        object.__setattr__(mutated, "ended_at", update.ended_at)
        if update.qa_status is not UNCHANGED:
            object.__setattr__(mutated, "qa_status", update.qa_status)
        self._overrides[run_id] = mutated
        return mutated


@pytest.mark.asyncio
async def test_policy_free_store_fails_the_property(
    store: InMemoryGenerationRunStore,
) -> None:
    """The negative control must be rejected by the property itself."""
    with pytest.raises(pytest.fail.Exception, match="DID NOT RAISE"):
        await check_quality_update(
            _PolicyFreeStore(store),
            QualityMode.QA_GATED,
            GenerationRunStatus.SUCCEEDED,
            UNCHANGED,
        )


def test_policy_free_update_would_violate_the_invariant() -> None:
    """Mutating the QA status without revalidation breaks the invariant.

    This is the mechanism behind the property's negative control: the store's
    policy, not the dataclass constructor alone, is what prevents the invalid
    combination from being persisted.
    """
    gated = dc.replace(
        make_generation_run(),
        status=GenerationRunStatus.RUNNING,
        quality_mode=QualityMode.QA_GATED,
        qa_status=QaStatus.PENDING,
        skip_qa_rationale=None,
    )
    passed = dc.replace(
        gated,
        status=GenerationRunStatus.SUCCEEDED,
        current_node=None,
        ended_at=NOW,
        qa_status=QaStatus.PASSED,
    )
    object.__setattr__(passed, "qa_status", QaStatus.PENDING)

    assert (passed.qa_status is QaStatus.PASSED) != (
        passed.status is GenerationRunStatus.SUCCEEDED
    ), "the control mutation must break the invariant"
    with pytest.raises(ValueError, match="qa_status"):
        apply_status_update(
            gated,
            GenerationRunStatusUpdate(
                status=GenerationRunStatus.SUCCEEDED,
                current_node=None,
                ended_at=NOW,
            ),
        )
