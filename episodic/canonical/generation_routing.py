"""Pure routing policy for the content-generation quality branches.

This module is the single statement of how a quality mode selects a branch,
which branch owns each terminal, how evaluator verdicts aggregate, and what
each terminal records. It holds no I/O and imports no framework, so graph
builders, graph runners and the launcher can all depend on it without
depending on each other.
"""

import dataclasses as dc
import enum
import typing as typ

from .domain_enums import GenerationRunStatus
from .generation_quality import QaStatus, QualityMode

if typ.TYPE_CHECKING:
    import collections.abc as cabc


class QualityBranch(enum.StrEnum):
    """Executable branch a quality mode selects."""

    DRAFT_WITHOUT_QA = "draft_without_qa"
    QA_GATED = "qa_gated"


class QualityVerdict(enum.StrEnum):
    """Outcome of one evaluator, or of aggregating several."""

    PASSED = "passed"
    FAILED = "failed"
    INCONCLUSIVE = "inconclusive"


class EvaluationRoute(enum.StrEnum):
    """Route taken after aggregating evaluator verdicts."""

    PASS = "pass"  # ruff: ignore[hardcoded-password-string] - route name, not a secret.
    ESCALATE = "escalate"


class GenerationTerminal(enum.StrEnum):
    """Terminal a completed generation-graph run reaches."""

    DRAFT_PERSISTED_WITHOUT_QA = "draft_persisted_without_qa"
    QA_PASSED_DRAFT_PERSISTED = "qa_passed_draft_persisted"
    QA_ESCALATED = "qa_escalated"


_TERMINAL_BRANCHES: dict[GenerationTerminal, QualityBranch] = {
    GenerationTerminal.DRAFT_PERSISTED_WITHOUT_QA: QualityBranch.DRAFT_WITHOUT_QA,
    GenerationTerminal.QA_PASSED_DRAFT_PERSISTED: QualityBranch.QA_GATED,
    GenerationTerminal.QA_ESCALATED: QualityBranch.QA_GATED,
}


def route_quality_mode(mode: QualityMode) -> QualityBranch:
    """Return the branch a quality mode executes.

    Parameters
    ----------
    mode : QualityMode
        Requested QA policy.

    Returns
    -------
    QualityBranch
        The one branch that mode owns.

    Examples
    --------
    >>> route_quality_mode(QualityMode.QA_GATED) is QualityBranch.QA_GATED
    True
    """
    match mode:
        case QualityMode.DRAFT_WITHOUT_QA:
            return QualityBranch.DRAFT_WITHOUT_QA
        case QualityMode.QA_GATED:
            return QualityBranch.QA_GATED
        case _:
            typ.assert_never(mode)


def branch_for_terminal(terminal: GenerationTerminal) -> QualityBranch:
    """Return the branch that owns a terminal."""
    return _TERMINAL_BRANCHES[terminal]


def aggregate_verdicts(verdicts: cabc.Iterable[QualityVerdict]) -> QualityVerdict:
    """Aggregate evaluator verdicts under the "all must pass" policy.

    Parameters
    ----------
    verdicts : collections.abc.Iterable[QualityVerdict]
        Verdicts to aggregate, in any order. Duplicates are harmless.

    Returns
    -------
    QualityVerdict
        ``failed`` if any verdict failed, otherwise ``inconclusive`` if any was
        inconclusive, otherwise ``passed``. An empty set is ``inconclusive``:
        with no evidence, nothing has passed.

    Examples
    --------
    >>> aggregate_verdicts([]) is QualityVerdict.INCONCLUSIVE
    True
    >>> aggregate_verdicts([QualityVerdict.PASSED]) is QualityVerdict.PASSED
    True
    """
    seen = set(verdicts)
    if QualityVerdict.FAILED in seen:
        return QualityVerdict.FAILED
    if QualityVerdict.INCONCLUSIVE in seen or not seen:
        return QualityVerdict.INCONCLUSIVE
    return QualityVerdict.PASSED


def route_after_evaluation(verdict: QualityVerdict) -> EvaluationRoute:
    """Return the evaluation route an aggregate verdict selects."""
    return (
        EvaluationRoute.PASS
        if verdict is QualityVerdict.PASSED
        else EvaluationRoute.ESCALATE
    )


@dc.dataclass(frozen=True, slots=True)
class TerminalOutcome:
    """Run status and QA status a terminal records.

    Attributes
    ----------
    status : GenerationRunStatus
        Terminal lifecycle status.
    qa_status : QaStatus
        QA status recorded with it.
    error_category : str | None
        Stable failure category, or ``None`` for a successful terminal.
    """

    status: GenerationRunStatus
    qa_status: QaStatus
    error_category: str | None


_TERMINAL_OUTCOMES: dict[GenerationTerminal, TerminalOutcome] = {
    GenerationTerminal.DRAFT_PERSISTED_WITHOUT_QA: TerminalOutcome(
        status=GenerationRunStatus.SUCCEEDED,
        qa_status=QaStatus.SKIPPED,
        error_category=None,
    ),
    GenerationTerminal.QA_PASSED_DRAFT_PERSISTED: TerminalOutcome(
        status=GenerationRunStatus.SUCCEEDED,
        qa_status=QaStatus.PASSED,
        error_category=None,
    ),
    GenerationTerminal.QA_ESCALATED: TerminalOutcome(
        status=GenerationRunStatus.FAILED,
        qa_status=QaStatus.FAILED,
        error_category="qa.escalation_required",
    ),
}


def terminal_outcome(terminal: GenerationTerminal) -> TerminalOutcome:
    """Return the run and QA status a terminal records."""
    return _TERMINAL_OUTCOMES[terminal]
