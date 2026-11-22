"""Tests for the pure quality-branch routing policy (INV-3, INV-4, INV-13).

``route_quality_mode`` must be total and injective, ``branch_for_terminal``
must be total, every branch must own at least one terminal, verdict aggregation
must be "all must pass", and an episode TEI update may record only the QA
statuses that represent a persisted draft.
"""

import datetime as dt
import typing as typ
import uuid

import hypothesis.strategies as st
import pytest
from hypothesis import example, given, settings

from episodic.canonical.domain import EpisodeTeiUpdate
from episodic.canonical.generation_quality import QaStatus, QualityMode
from episodic.canonical.generation_routing import (
    EvaluationRoute,
    GenerationTerminal,
    QualityBranch,
    QualityVerdict,
    aggregate_verdicts,
    branch_for_terminal,
    route_after_evaluation,
    route_quality_mode,
)

NOW = dt.datetime(2026, 6, 4, 8, 0, tzinfo=dt.UTC)


@pytest.mark.parametrize("mode", tuple(QualityMode))
def test_route_quality_mode_returns_a_branch(mode: QualityMode) -> None:
    """Every quality mode routes to exactly one branch."""
    branch = route_quality_mode(mode)
    assert isinstance(branch, QualityBranch), f"branch={branch!r}"


def test_route_quality_mode_is_injective() -> None:
    """Distinct quality modes must map to distinct branches."""
    branches = {route_quality_mode(mode) for mode in QualityMode}
    assert len(branches) == len(tuple(QualityMode)), (
        f"branches={branches!r}; distinct modes must not share a branch"
    )


@pytest.mark.parametrize("terminal", tuple(GenerationTerminal))
def test_branch_for_terminal_is_total(terminal: GenerationTerminal) -> None:
    """Every terminal belongs to exactly one branch."""
    branch = branch_for_terminal(terminal)
    assert isinstance(branch, QualityBranch), f"branch={branch!r}"


def test_every_branch_owns_a_terminal() -> None:
    """Each branch must have at least one terminal."""
    owned = {branch_for_terminal(terminal) for terminal in GenerationTerminal}
    assert owned == set(QualityBranch), f"branches without a terminal: {owned!r}"


@pytest.mark.parametrize("verdict", tuple(QualityVerdict))
def test_route_after_evaluation_only_passes_on_success(verdict: QualityVerdict) -> None:
    """Only a passed verdict takes the persistence route."""
    route = route_after_evaluation(verdict)
    expected = (
        EvaluationRoute.PASS
        if verdict is QualityVerdict.PASSED
        else (EvaluationRoute.ESCALATE)
    )
    assert route is expected, f"verdict={verdict!r} route={route!r}"


def _aggregate_oracle(verdicts: list[QualityVerdict]) -> QualityVerdict:
    """State the aggregation rule literally, independently of the production code."""
    if not verdicts:
        return QualityVerdict.INCONCLUSIVE
    if any(verdict is QualityVerdict.FAILED for verdict in verdicts):
        return QualityVerdict.FAILED
    if any(verdict is QualityVerdict.INCONCLUSIVE for verdict in verdicts):
        return QualityVerdict.INCONCLUSIVE
    return QualityVerdict.PASSED


def _any_passes(verdicts: list[QualityVerdict]) -> QualityVerdict:
    """Implement the rejected "any passes" alternative for a negative control."""
    if any(verdict is QualityVerdict.PASSED for verdict in verdicts):
        return QualityVerdict.PASSED
    return QualityVerdict.FAILED


@example([])
@example([QualityVerdict.PASSED])
@example([QualityVerdict.PASSED, QualityVerdict.FAILED])
@example([QualityVerdict.PASSED, QualityVerdict.INCONCLUSIVE])
@given(verdicts=st.lists(st.sampled_from(QualityVerdict)))
@settings(max_examples=100)
def test_aggregate_verdicts_all_must_pass(verdicts: list[QualityVerdict]) -> None:
    """Aggregation matches the literal rule and is order- and repeat-invariant."""
    aggregate = aggregate_verdicts(verdicts)

    assert aggregate is _aggregate_oracle(verdicts), f"verdicts={verdicts!r}"
    assert aggregate_verdicts(list(reversed(verdicts))) is aggregate, (
        f"aggregation must not depend on order: {verdicts!r}"
    )
    if verdicts:
        assert aggregate_verdicts([*verdicts, verdicts[0]]) is aggregate, (
            f"aggregation must not depend on duplication: {verdicts!r}"
        )


def test_any_passes_control_disagrees_with_production() -> None:
    """The rejected alternative must fail the property's witness."""
    witness = [QualityVerdict.PASSED, QualityVerdict.FAILED]
    assert _any_passes(witness) is QualityVerdict.PASSED, (
        "the control must implement any-passes"
    )
    assert aggregate_verdicts(witness) is QualityVerdict.FAILED, (
        "any-passes must not satisfy all-must-pass"
    )


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


def test_assert_never_covers_every_quality_mode() -> None:
    """Routing is exhaustive over the enum the type checker already narrows."""
    covered: set[QualityMode] = set()
    for mode in QualityMode:
        match mode:
            case QualityMode.DRAFT_WITHOUT_QA | QualityMode.QA_GATED:
                covered.add(mode)
            case _:
                typ.assert_never(mode)
    assert covered == set(QualityMode), "every mode must be classified"
