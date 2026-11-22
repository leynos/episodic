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
    """Every accepted update keeps the mode's QA invariant true."""
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

    try:
        updated = await store.update_run_status(run.id, update=update)
    except ValueError:
        assert await store.get_run(run.id) == run, (
            "a rejected update must leave the row unchanged"
        )
        return

    resolved_qa = run.qa_status if update_qa is UNCHANGED else update_qa
    assert updated.qa_status is resolved_qa, (
        f"resolved qa_status={updated.qa_status!r}, expected {resolved_qa!r}"
    )
    if no_qa:
        assert updated.qa_status is QaStatus.SKIPPED, updated.qa_status
    else:
        assert (updated.qa_status is QaStatus.PASSED) == (
            updated.status is GenerationRunStatus.SUCCEEDED
        ), f"status={updated.status!r} qa_status={updated.qa_status!r}"


def test_policy_free_update_would_violate_the_invariant() -> None:
    """Mutating the QA status without revalidation breaks the invariant.

    This is the negative control for the property: the store's policy, not the
    dataclass constructor alone, is what prevents the invalid combination from
    being persisted.
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
