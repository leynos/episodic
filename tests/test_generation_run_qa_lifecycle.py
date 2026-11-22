"""QA-gated lifecycle rows for the generation-run domain model."""

import dataclasses as dc
import datetime as dt
import uuid

import pytest

from episodic.canonical.domain import GenerationRun, GenerationRunStatus
from episodic.canonical.generation_quality import QaStatus, QualityMode

NOW = dt.datetime(2026, 6, 4, 8, 0, tzinfo=dt.UTC)


@pytest.fixture
def generation_run() -> GenerationRun:
    """Build a pending no-QA generation run for tests."""
    return GenerationRun(
        id=uuid.UUID("018fdcf0-0000-7000-8000-000000000001"),
        episode_id=uuid.UUID("018fdcf0-0000-7000-8000-000000000002"),
        source_bundle_id=uuid.UUID("018fdcf0-0000-7000-8000-000000000003"),
        actor="editor@example.com",
        status=GenerationRunStatus.PENDING,
        current_node=None,
        budget_snapshot={"limit": 10},
        configuration={"model": "gpt-4.1"},
        created_at=NOW,
        updated_at=NOW,
        started_at=None,
        ended_at=None,
        error_message=None,
        quality_mode=QualityMode.DRAFT_WITHOUT_QA,
        qa_status=QaStatus.SKIPPED,
        skip_qa_rationale="No-QA vertical-slice draft.",
    )


def test_generation_run_accepts_qa_gated_pending_metadata(
    generation_run: GenerationRun,
) -> None:
    """A QA-gated run starts pending with no skip rationale."""
    run = dc.replace(
        generation_run,
        quality_mode=QualityMode.QA_GATED,
        qa_status=QaStatus.PENDING,
        skip_qa_rationale=None,
    )

    assert run.quality_mode is QualityMode.QA_GATED, (
        f"expected qa_gated mode, got {run.quality_mode!r}"
    )
    assert run.qa_status is QaStatus.PENDING, (
        f"expected pending QA status, got {run.qa_status!r}"
    )
    assert run.skip_qa_rationale is None, (
        f"expected no rationale, got {run.skip_qa_rationale!r}"
    )


def test_generation_run_accepts_qa_gated_success_after_a_pass(
    generation_run: GenerationRun,
) -> None:
    """A succeeded QA-gated run records a passed QA status."""
    run = dc.replace(
        generation_run,
        quality_mode=QualityMode.QA_GATED,
        qa_status=QaStatus.PASSED,
        skip_qa_rationale=None,
        status=GenerationRunStatus.SUCCEEDED,
        ended_at=NOW,
    )

    assert run.status is GenerationRunStatus.SUCCEEDED, (
        f"expected a succeeded run, got {run.status!r}"
    )
    assert run.qa_status is QaStatus.PASSED, (
        f"expected a passed QA status, got {run.qa_status!r}"
    )


@pytest.mark.parametrize(
    ("changes", "match"),
    [
        pytest.param(
            {"qa_status": QaStatus.SKIPPED, "skip_qa_rationale": None},
            "qa_status",
            id="skipped-status",
        ),
        pytest.param(
            {"qa_status": None, "skip_qa_rationale": None},
            "qa_status",
            id="missing-status",
        ),
        pytest.param(
            {"qa_status": QaStatus.PASSED, "skip_qa_rationale": None},
            "passed",
            id="passed-before-success",
        ),
        pytest.param(
            {"qa_status": QaStatus.PENDING, "skip_qa_rationale": "reason"},
            "skip_qa_rationale",
            id="gated-with-rationale",
        ),
    ],
)
def test_generation_run_rejects_invalid_qa_gated_metadata(
    generation_run: GenerationRun,
    changes: dict[str, object],
    match: str,
) -> None:
    """QA-gated metadata must satisfy the quality policy."""
    with pytest.raises(ValueError, match=match):
        dc.replace(
            generation_run,
            quality_mode=QualityMode.QA_GATED,
            **changes,
        )
