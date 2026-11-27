"""Tests for the resolved generation-run status update (INV-2, D5).

``apply_status_update`` is the one place that resolves the ``UNCHANGED`` QA
sentinel and re-validates the resulting run, so both store adapters share a
single policy. These tests pin the sentinel behaviour, the re-validation, and
the contrast with the error fields.
"""

import dataclasses as dc
import datetime as dt
import uuid

import pytest

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

NOW = dt.datetime(2026, 6, 4, 8, 0, tzinfo=dt.UTC)


@dc.dataclass(frozen=True, slots=True)
class _RunSpec:
    """Lifecycle and quality fields for a generated run."""

    status: GenerationRunStatus
    quality_mode: QualityMode
    qa_status: QaStatus
    skip_qa_rationale: str | None
    current_node: str | None
    ended_at: dt.datetime | None


def _run(spec: _RunSpec) -> GenerationRun:
    """Build a run in the requested lifecycle and quality state."""
    return GenerationRun(
        id=uuid.UUID("018fdcf0-0000-7000-8000-000000000001"),
        episode_id=uuid.UUID("018fdcf0-0000-7000-8000-000000000002"),
        source_bundle_id=uuid.UUID("018fdcf0-0000-7000-8000-000000000003"),
        actor="editor@example.com",
        status=spec.status,
        current_node=spec.current_node,
        budget_snapshot={},
        configuration={},
        created_at=NOW,
        updated_at=NOW,
        started_at=NOW,
        ended_at=spec.ended_at,
        error_message=None,
        quality_mode=spec.quality_mode,
        qa_status=spec.qa_status,
        skip_qa_rationale=spec.skip_qa_rationale,
    )


def _no_qa_run(
    status: GenerationRunStatus = GenerationRunStatus.RUNNING,
) -> GenerationRun:
    """Build a running no-QA run."""
    return _run(
        _RunSpec(
            status=status,
            quality_mode=QualityMode.DRAFT_WITHOUT_QA,
            qa_status=QaStatus.SKIPPED,
            skip_qa_rationale="No-QA vertical-slice draft.",
            current_node="draft",
            ended_at=None,
        )
    )


def _gated_run(
    status: GenerationRunStatus = GenerationRunStatus.RUNNING,
    qa_status: QaStatus = QaStatus.PENDING,
) -> GenerationRun:
    """Build a QA-gated run in the given lifecycle and QA state."""
    terminal = status.is_terminal()
    return _run(
        _RunSpec(
            status=status,
            quality_mode=QualityMode.QA_GATED,
            qa_status=qa_status,
            skip_qa_rationale=None,
            current_node=None if terminal else "evaluate",
            ended_at=NOW if terminal else None,
        )
    )


def test_unchanged_sentinel_keeps_the_persisted_qa_status() -> None:
    """An omitted QA status must not clear a QA outcome that is still open."""
    run = _gated_run()

    resolved = apply_status_update(
        run,
        GenerationRunStatusUpdate(
            status=GenerationRunStatus.RUNNING,
            current_node="evaluate",
            ended_at=None,
        ),
    )

    assert resolved.qa_status is QaStatus.PENDING, (
        f"sentinel must keep the persisted status, got {resolved.qa_status!r}"
    )


def test_error_fields_still_clear_when_omitted() -> None:
    """The contrast in the command contract: error fields clear, QA does not."""
    run = dc.replace(
        _gated_run(),
        error_message="previous failure",
        error_category="provider.transient",
    )

    resolved = apply_status_update(
        run,
        GenerationRunStatusUpdate(
            status=GenerationRunStatus.FAILED,
            current_node=None,
            ended_at=NOW,
        ),
    )

    assert resolved.error_message is None, "omitted error_message clears"
    assert resolved.error_category is None, "omitted error_category clears"
    assert resolved.qa_status is QaStatus.PENDING, "omitted qa_status is unchanged"


def test_explicit_qa_status_is_applied() -> None:
    """An explicit QA status replaces the persisted value."""
    resolved = apply_status_update(
        _gated_run(),
        GenerationRunStatusUpdate(
            status=GenerationRunStatus.SUCCEEDED,
            current_node=None,
            ended_at=NOW,
            qa_status=QaStatus.PASSED,
        ),
    )

    assert resolved.status is GenerationRunStatus.SUCCEEDED, (
        f"resolved status={resolved.status!r}"
    )
    assert resolved.qa_status is QaStatus.PASSED, (
        f"resolved qa_status={resolved.qa_status!r}"
    )


@pytest.mark.parametrize(
    ("run", "update", "match"),
    [
        pytest.param(
            _gated_run(qa_status=QaStatus.FAILED),
            GenerationRunStatusUpdate(
                status=GenerationRunStatus.RUNNING,
                current_node="evaluate",
                ended_at=None,
                qa_status=QaStatus.PASSED,
            ),
            "passed",
            id="passed-while-running",
        ),
        pytest.param(
            _no_qa_run(),
            GenerationRunStatusUpdate(
                status=GenerationRunStatus.SUCCEEDED,
                current_node=None,
                ended_at=NOW,
                qa_status=QaStatus.PENDING,
            ),
            "qa_status",
            id="no-qa-cannot-become-pending",
        ),
        pytest.param(
            _no_qa_run(),
            GenerationRunStatusUpdate(
                status=GenerationRunStatus.SUCCEEDED,
                current_node="draft",
                ended_at=NOW,
            ),
            "current node",
            id="terminal-with-current-node",
        ),
    ],
)
def test_invalid_resolution_raises(
    run: GenerationRun,
    update: GenerationRunStatusUpdate,
    match: str,
) -> None:
    """A combination the domain forbids is rejected before any write."""
    with pytest.raises(ValueError, match=match):
        apply_status_update(run, update)


def test_sentinel_is_not_a_qa_status() -> None:
    """The sentinel is deliberately outside the persisted QA-status enum."""
    assert UNCHANGED not in set(QaStatus), "UNCHANGED must not be persistable"
