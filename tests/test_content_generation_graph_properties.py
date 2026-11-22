"""Property tests for branch ownership in the content-generation graph (INV-5).

Each example drives the production runner with a recording step port and
scripted evaluators. The result must take exactly one of two forms: a single
terminal owned by the run's branch, with only that branch's steps called, or a
propagated fault after which no terminal step is recorded. A second invocation
with the same input must produce an identical step log and outcome.
"""

import collections
import dataclasses as dc
import typing as typ
import uuid

import hypothesis.strategies as st
import pytest
from hypothesis import example, given, settings

from episodic.canonical.generation_graph_ports import (
    ContentGenerationRequest,
    QualityEvaluation,
    QualityEvaluationUnavailableError,
    QualityEvaluatorSet,
)
from episodic.canonical.generation_quality import QaStatus, QualityMode
from episodic.canonical.generation_routing import (
    GenerationTerminal,
    QualityVerdict,
    branch_for_terminal,
    route_quality_mode,
)
from episodic.orchestration._content_graph_state import (
    NODE_OWNERSHIP,
)
from episodic.orchestration.content_generation import LangGraphContentGenerationGraph
from tests._content_graph_fakes import (
    FAULT_STEPS,
    RecordingSteps,
    ScriptedEvaluator,
    expected_aggregate,
)

if typ.TYPE_CHECKING:
    import collections.abc as cabc


_BEHAVIOURS: tuple[str, ...] = (
    "passed",
    "failed",
    "inconclusive",
    "raise",
    "timeout",
    "cancel",
)
_TIMEOUT_SECONDS = 0.01
_RUN_ID = "018fdcf0-0000-7000-8000-000000000001"


@dc.dataclass(frozen=True, slots=True)
class _Outcome:
    """Terminal or error produced by one graph run."""

    terminal: GenerationTerminal | None
    error: BaseException | None


def _graph(behaviours: cabc.Sequence[str]) -> LangGraphContentGenerationGraph:
    """Build a graph over scripted evaluators."""
    evaluators = tuple(
        ScriptedEvaluator(f"evaluator-{index}", behaviour)
        for index, behaviour in enumerate(behaviours)
    )
    evaluator_set = QualityEvaluatorSet(
        evaluators,
        evaluator_timeout_seconds=_TIMEOUT_SECONDS,
    )
    return LangGraphContentGenerationGraph(evaluator_set)


async def _invoke(
    graph: LangGraphContentGenerationGraph,
    mode: QualityMode,
    steps: RecordingSteps,
) -> _Outcome:
    """Run the graph and capture its terminal or expected error."""
    request = ContentGenerationRequest(
        run_id=uuid.UUID(_RUN_ID),
        quality_mode=mode,
    )
    try:
        terminal = await graph.run(request, steps=steps)
    except QualityEvaluationUnavailableError as exc:
        return _Outcome(None, exc)
    except RuntimeError as exc:
        return _Outcome(None, exc)
    return _Outcome(terminal, None)


def _expected_steps(
    mode: QualityMode,
    behaviours: cabc.Sequence[str],
    fault: str | None,
) -> tuple[str, ...]:
    """State the exact step log the graph must produce."""
    if mode is QualityMode.QA_GATED and not behaviours:
        return ()
    steps = ["initialize", "generate_draft"]
    if mode is QualityMode.QA_GATED:
        passed = expected_aggregate(behaviours) is QualityVerdict.PASSED
        persist = "complete_with_draft" if passed else "escalate"
        steps.extend(["begin_evaluation", persist])
    else:
        steps.append("complete_with_draft")
    if fault is not None and fault in steps:
        steps = steps[: steps.index(fault) + 1]
    return tuple(steps)


def _expected_terminal(
    mode: QualityMode,
    behaviours: cabc.Sequence[str],
    fault: str | None,
) -> GenerationTerminal | None:
    """State the terminal the graph must reach, or None after a fault."""
    steps = _expected_steps(mode, behaviours, fault)
    if fault is not None and fault in steps:
        return None
    if mode is QualityMode.DRAFT_WITHOUT_QA:
        return GenerationTerminal.DRAFT_PERSISTED_WITHOUT_QA
    if not behaviours:
        return None
    if expected_aggregate(behaviours) is QualityVerdict.PASSED:
        return GenerationTerminal.QA_PASSED_DRAFT_PERSISTED
    return GenerationTerminal.QA_ESCALATED


def _visited_nodes(mode: QualityMode, step_names: cabc.Sequence[str]) -> set[str]:
    """Return the graph nodes a step log proves the run visited."""
    visited: set[str] = {"initialize"}
    if "generate_draft" in step_names:
        visited.add(
            "generate_qa_candidate"
            if mode is QualityMode.QA_GATED
            else "generate_draft_without_qa"
        )
    if "begin_evaluation" in step_names:
        visited.add("evaluate")
    if "complete_with_draft" in step_names:
        visited.add(
            "persist_qa_passed_draft"
            if mode is QualityMode.QA_GATED
            else "persist_draft_without_qa"
        )
    if "escalate" in step_names:
        visited.add("escalate")
    return visited


def assert_branch_ownership(
    mode: QualityMode,
    step_names: cabc.Sequence[str],
    terminal: GenerationTerminal | None,
) -> None:
    """Reject a trace that visits a node its quality branch does not own."""
    branch = route_quality_mode(mode)
    if mode is QualityMode.DRAFT_WITHOUT_QA:
        assert "begin_evaluation" not in step_names, "no-QA runs never evaluate"
        assert "escalate" not in step_names, "no-QA runs never escalate"
    for node in _visited_nodes(mode, step_names):
        owner = NODE_OWNERSHIP[node]
        assert owner in {None, branch}, f"{node} belongs to {owner}, not {branch}"
    if terminal is not None:
        assert branch_for_terminal(terminal) is branch, (
            f"{terminal} does not belong to {branch}"
        )


_FAULT_LABELS: dict[str, str] = {
    "initialize": "fault@initialize",
    "generate_draft": "fault@generate",
    "begin_evaluation": "fault@begin_evaluation",
    "complete_with_draft": "fault@complete_with_draft",
    "escalate": "fault@escalate",
}


def _classify(
    mode: QualityMode,
    behaviours: cabc.Sequence[str],
    fault: str | None,
    outcome: _Outcome,
) -> str:
    """Name the observation class an example reached."""
    if isinstance(outcome.error, QualityEvaluationUnavailableError):
        label = "qa_unavailable"
    elif outcome.error is not None:
        label = _FAULT_LABELS[typ.cast("str", fault)]
    elif mode is QualityMode.DRAFT_WITHOUT_QA:
        label = "no_qa_persisted"
    else:
        label = _aggregate_label(expected_aggregate(behaviours), behaviours)
    return label


def _aggregate_label(
    aggregate: QualityVerdict,
    behaviours: cabc.Sequence[str],
) -> str:
    """Name the escalation class an aggregate verdict reached."""
    if aggregate is QualityVerdict.PASSED:
        return "qa_passed"
    if aggregate is QualityVerdict.FAILED:
        return "qa_escalated_failed"
    if "timeout" in behaviours:
        return "qa_escalated_timeout"
    return "qa_escalated_inconclusive"


async def _check_case(
    mode: QualityMode,
    behaviours: cabc.Sequence[str],
    fault: str | None,
    reached: collections.Counter[str] | None = None,
) -> None:
    """Assert the property for one generated input and optionally count it."""
    expected_steps = _expected_steps(mode, behaviours, fault)
    expected_terminal = _expected_terminal(mode, behaviours, fault)
    steps = RecordingSteps(fault_step=fault)
    outcome = await _invoke(_graph(behaviours), mode, steps)
    replay = RecordingSteps(fault_step=fault)
    replay_outcome = await _invoke(_graph(behaviours), mode, replay)

    assert tuple(steps.step_names()) == expected_steps, (
        f"step log {steps.step_names()} != expected {expected_steps}"
    )
    assert replay.step_names() == steps.step_names(), "step log must be deterministic"
    assert_branch_ownership(mode, steps.step_names(), outcome.terminal)
    if outcome.error is not None:
        assert expected_terminal is None, f"unexpected error {outcome.error!r}"
        assert type(replay_outcome.error) is type(outcome.error), (
            "a fault must be deterministic"
        )
    else:
        assert outcome.terminal == expected_terminal, (
            f"terminal {outcome.terminal!r} != expected {expected_terminal!r}"
        )
        assert replay_outcome.terminal == outcome.terminal, (
            "terminal must be deterministic"
        )
    _assert_terminal_details(outcome.terminal, steps, behaviours)
    if reached is not None:
        reached[_classify(mode, behaviours, fault, outcome)] += 1


def _assert_terminal_details(
    terminal: GenerationTerminal | None,
    steps: RecordingSteps,
    behaviours: cabc.Sequence[str],
) -> None:
    """Assert the QA status and evaluations a terminal recorded."""
    if terminal is GenerationTerminal.QA_PASSED_DRAFT_PERSISTED:
        qa_status, evaluations = typ.cast(
            "tuple[QaStatus, tuple[QualityEvaluation, ...]]",
            steps.detail_for("complete_with_draft"),
        )
        assert qa_status is QaStatus.PASSED, f"persisted qa_status {qa_status!r}"
        assert all(item.verdict is QualityVerdict.PASSED for item in evaluations), (
            "every evaluation on the pass route must have passed"
        )
    if terminal is GenerationTerminal.QA_ESCALATED:
        verdict, evaluations = typ.cast(
            "tuple[QualityVerdict, tuple[QualityEvaluation, ...]]",
            steps.detail_for("escalate"),
        )
        expected = expected_aggregate(behaviours)
        assert verdict is expected, (
            f"escalation verdict {verdict!r} != aggregate {expected!r}"
        )
        assert evaluations, "escalation carries the evaluator results"


@pytest.mark.asyncio
@example(QualityMode.DRAFT_WITHOUT_QA, (), None)
@example(QualityMode.QA_GATED, (), None)
@example(QualityMode.QA_GATED, ("passed",), None)
@example(QualityMode.QA_GATED, ("failed",), None)
@example(QualityMode.QA_GATED, ("inconclusive",), None)
@example(QualityMode.QA_GATED, ("timeout",), None)
@example(QualityMode.QA_GATED, ("passed", "failed"), None)
@example(QualityMode.DRAFT_WITHOUT_QA, (), "initialize")
@example(QualityMode.DRAFT_WITHOUT_QA, (), "generate_draft")
@example(QualityMode.QA_GATED, ("passed",), "begin_evaluation")
@example(QualityMode.QA_GATED, ("passed",), "complete_with_draft")
@example(QualityMode.QA_GATED, ("failed",), "escalate")
@given(
    mode=st.sampled_from(tuple(QualityMode)),
    behaviours=st.lists(
        st.sampled_from(_BEHAVIOURS),
        max_size=3,
    ),
    fault=st.one_of(st.none(), st.sampled_from(FAULT_STEPS)),
)
@settings(deadline=None, max_examples=100)
async def test_branch_ownership_property(
    mode: QualityMode,
    behaviours: list[str],
    fault: str | None,
) -> None:
    """Every run visits only its branch's nodes and reaches one owned terminal."""
    await _check_case(mode, behaviours, fault)


_EXPECTED_CLASSES: frozenset[str] = frozenset({
    "no_qa_persisted",
    "qa_passed",
    "qa_escalated_failed",
    "qa_escalated_inconclusive",
    "qa_escalated_timeout",
    "qa_unavailable",
    "fault@initialize",
    "fault@generate",
    "fault@begin_evaluation",
    "fault@complete_with_draft",
    "fault@escalate",
})

_MATRIX: tuple[tuple[QualityMode, tuple[str, ...], str | None], ...] = (
    (QualityMode.DRAFT_WITHOUT_QA, (), None),
    (QualityMode.QA_GATED, ("passed",), None),
    (QualityMode.QA_GATED, ("failed",), None),
    (QualityMode.QA_GATED, ("inconclusive",), None),
    (QualityMode.QA_GATED, ("timeout",), None),
    (QualityMode.QA_GATED, (), None),
    (QualityMode.DRAFT_WITHOUT_QA, (), "initialize"),
    (QualityMode.DRAFT_WITHOUT_QA, (), "generate_draft"),
    (QualityMode.QA_GATED, ("passed",), "begin_evaluation"),
    (QualityMode.QA_GATED, ("passed",), "complete_with_draft"),
    (QualityMode.QA_GATED, ("failed",), "escalate"),
)


@pytest.mark.asyncio
async def test_property_reaches_every_class() -> None:
    """The property's witness matrix reaches each documented class."""
    reached: collections.Counter[str] = collections.Counter()
    for mode, behaviours, fault in _MATRIX:
        await _check_case(mode, behaviours, fault, reached)
    assert set(reached) == _EXPECTED_CLASSES, f"reached classes: {sorted(reached)}"


def test_ownership_checker_rejects_bad_traces() -> None:
    """The checker must reject a foreign node and a foreign terminal."""
    with pytest.raises(AssertionError, match="no-QA runs never evaluate"):
        assert_branch_ownership(
            QualityMode.DRAFT_WITHOUT_QA,
            ("initialize", "generate_draft", "begin_evaluation"),
            None,
        )
    with pytest.raises(AssertionError, match="does not belong"):
        assert_branch_ownership(
            QualityMode.DRAFT_WITHOUT_QA,
            ("initialize", "generate_draft", "complete_with_draft"),
            GenerationTerminal.QA_ESCALATED,
        )
