"""Exhaustive tests for the generation quality-metadata policy (INV-1).

``GenerationRun`` must construct if and only if
``(quality_mode, status, qa_status, skip_qa_rationale)`` satisfies decision D5.
The expected verdicts are a literal truth table in
``tests/data/generation_quality_policy.csv``: 2 modes x 6 statuses x 5 QA
values x 3 rationale classes. The test compares against that table rather than
re-deriving the rule, so a change to the policy has to change the data.
"""

import csv
import dataclasses as dc
import datetime as dt
import itertools
import uuid
from pathlib import Path

import hypothesis.strategies as st
import pytest
from hypothesis import given, settings

from episodic.canonical.domain import (
    EpisodeTeiUpdate,
    GenerationRun,
    GenerationRunStatus,
)
from episodic.canonical.generation_quality import QaStatus, QualityMode

NOW = dt.datetime(2026, 6, 4, 8, 0, tzinfo=dt.UTC)
_TABLE_PATH = Path(__file__).parent / "data" / "generation_quality_policy.csv"

_STATUSES: tuple[GenerationRunStatus, ...] = tuple(GenerationRunStatus)
_QA_VALUES: tuple[QaStatus | None, ...] = (
    QaStatus.SKIPPED,
    QaStatus.PENDING,
    QaStatus.PASSED,
    QaStatus.FAILED,
    None,
)
_RATIONALES: dict[str, str | None] = {
    "none": None,
    "blank": "   ",
    "non_blank": "No-QA vertical-slice draft.",
}


@dc.dataclass(frozen=True, slots=True)
class _Row:
    """One literal truth-table row."""

    quality_mode: QualityMode
    status: GenerationRunStatus
    qa_status: QaStatus | None
    rationale: str | None
    is_valid: bool


def _parse_qa_status(value: str) -> QaStatus | None:
    """Return the QA-status value a table cell names."""
    return None if value == "none" else QaStatus(value)


def _table() -> tuple[_Row, ...]:
    """Read the literal truth table from its data file."""
    with _TABLE_PATH.open(newline="", encoding="utf-8") as handle:
        return tuple(
            _Row(
                quality_mode=QualityMode(record["quality_mode"]),
                status=GenerationRunStatus(record["status"]),
                qa_status=_parse_qa_status(record["qa_status"]),
                rationale=_RATIONALES[record["rationale"]],
                is_valid=record["valid"] == "true",
            )
            for record in csv.DictReader(handle)
        )


def _build(row: _Row) -> GenerationRun:
    """Construct the run one table row describes."""
    return GenerationRun(
        id=uuid.UUID("018fdcf0-0000-7000-8000-000000000001"),
        episode_id=uuid.UUID("018fdcf0-0000-7000-8000-000000000002"),
        source_bundle_id=uuid.UUID("018fdcf0-0000-7000-8000-000000000003"),
        actor="editor@example.com",
        status=row.status,
        current_node=None,
        budget_snapshot={},
        configuration={},
        created_at=NOW,
        updated_at=NOW,
        started_at=None,
        ended_at=NOW if row.status.is_terminal() else None,
        error_message=None,
        quality_mode=row.quality_mode,
        qa_status=row.qa_status,
        skip_qa_rationale=row.rationale,
    )


def _row_id(row: _Row) -> str:
    """Return a readable pytest identifier for one table row."""
    qa_status = "none" if row.qa_status is None else row.qa_status.value
    rationale = "none" if row.rationale is None else row.rationale.strip() or "blank"
    return f"{row.quality_mode.value}-{row.status.value}-{qa_status}-{rationale}"


_TABLE = _table()


def test_truth_table_covers_the_finite_product() -> None:
    """The literal table must cover every cell exactly once, both verdicts."""
    cells = [
        (row.quality_mode, row.status, row.qa_status, row.rationale) for row in _TABLE
    ]
    expected = set(
        itertools.product(
            tuple(QualityMode),
            _STATUSES,
            _QA_VALUES,
            _RATIONALES.values(),
        )
    )
    assert len(cells) == len(expected) == 180, (
        f"expected 180 unique cells, got {len(cells)} rows and "
        f"{len(expected)} expected cells"
    )
    assert set(cells) == expected, "the table must cover the finite product"
    for mode in QualityMode:
        verdicts = {row.is_valid for row in _TABLE if row.quality_mode is mode}
        assert verdicts == {True, False}, (
            f"{mode} must have both accepted and rejected cells"
        )


@pytest.mark.parametrize(
    "row",
    _TABLE,
    ids=[_row_id(row) for row in _TABLE],
)
def test_quality_metadata_policy(row: _Row) -> None:
    """Run construction matches the literal accept/reject verdict."""
    if row.is_valid:
        run = _build(row)
        assert run.quality_mode is row.quality_mode, (
            f"quality_mode={run.quality_mode!r}"
        )
        assert run.qa_status is row.qa_status, f"qa_status={run.qa_status!r}"
        assert run.skip_qa_rationale == row.rationale, (
            f"skip_qa_rationale={run.skip_qa_rationale!r}"
        )
    else:
        with pytest.raises(ValueError, match=r"qa_status|skip_qa_rationale"):
            _build(row)


def test_no_qa_messages_are_unchanged() -> None:
    """The no-QA slice keeps its historical rejection messages verbatim."""
    with pytest.raises(
        ValueError,
        match=r"qa_status must be skipped for draft_without_qa runs\.",
    ):
        _build(
            _Row(
                quality_mode=QualityMode.DRAFT_WITHOUT_QA,
                status=GenerationRunStatus.PENDING,
                qa_status=None,
                rationale="Valid rationale.",
                is_valid=False,
            )
        )
    with pytest.raises(
        ValueError,
        match=r"skip_qa_rationale must be a non-empty string\.",
    ):
        _build(
            _Row(
                quality_mode=QualityMode.DRAFT_WITHOUT_QA,
                status=GenerationRunStatus.PENDING,
                qa_status=QaStatus.SKIPPED,
                rationale=" ",
                is_valid=False,
            )
        )


@given(rationale=st.text())
@settings(max_examples=100)
def test_no_qa_rationale_accepts_exactly_non_whitespace_text(rationale: str) -> None:
    """A no-QA rationale is accepted exactly when it has a non-space character."""
    row = _Row(
        quality_mode=QualityMode.DRAFT_WITHOUT_QA,
        status=GenerationRunStatus.PENDING,
        qa_status=QaStatus.SKIPPED,
        rationale=rationale,
        is_valid=bool(rationale.strip()),
    )
    if row.is_valid:
        assert _build(row).skip_qa_rationale == rationale, (
            f"rationale {rationale!r} should have been accepted"
        )
    else:
        with pytest.raises(ValueError, match="skip_qa_rationale"):
            _build(row)


def _tei_update(qa_status: QaStatus) -> EpisodeTeiUpdate:
    """Build an episode TEI update recording one QA status."""
    return EpisodeTeiUpdate(
        tei_xml="<TEI><text><body><p>Draft.</p></body></text></TEI>",
        qa_status=qa_status,
        last_generation_run_id=uuid.UUID("018fdcf0-0000-7000-8000-000000000001"),
        expected_revision=1,
        updated_at=NOW,
    )


@pytest.mark.parametrize("qa_status", tuple(QaStatus))
def test_episode_tei_update_records_only_persisted_drafts(
    qa_status: QaStatus,
) -> None:
    """Episode TEI may record a skipped or passed draft, and nothing else."""
    if qa_status in {QaStatus.SKIPPED, QaStatus.PASSED}:
        assert _tei_update(qa_status).qa_status is qa_status, (
            f"{qa_status} describes a persisted draft"
        )
    else:
        with pytest.raises(ValueError, match="qa_status"):
            _tei_update(qa_status)
