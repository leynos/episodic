"""Ports and value objects for the content-generation graph.

The graph runner depends on these protocols; the launcher implements the step
port, and evaluator adapters implement :class:`QualityEvaluatorPort`. Nothing
here imports LangGraph, so node functions and application code can be written
against a stable domain contract.

A per-run *run session* implements :class:`ContentGenerationSteps`. Graph
nodes reach run state only through it, so the launcher task that claimed the
run remains its single writer. Evaluators run under
:attr:`QualityEvaluatorSet.evaluator_timeout_seconds` so a hung adapter cannot
hold a launcher permit indefinitely.
"""

import dataclasses as dc
import typing as typ

from .generation_quality import QaStatus, QualityMode

if typ.TYPE_CHECKING:
    import uuid

    from .generation_routing import GenerationTerminal, QualityVerdict


@dc.dataclass(frozen=True, slots=True)
class EvaluationSubject:
    """Draft content an evaluator judges.

    Attributes
    ----------
    run_id : uuid.UUID
        Generation run whose draft is under evaluation.
    episode_id : uuid.UUID
        Episode the draft will update if it passes.
    tei_xml : str
        Generated TEI-P5 script.
    content_hash : str
        Content hash recorded for the generated draft.
    """

    run_id: uuid.UUID
    episode_id: uuid.UUID
    tei_xml: str
    content_hash: str


@dc.dataclass(frozen=True, slots=True)
class QualityEvaluation:
    """One evaluator's result.

    Attributes
    ----------
    evaluator : str
        Stable evaluator slug, used in events and metric labels.
    verdict : QualityVerdict
        Evaluator verdict.
    summary : str | None
        Optional human-readable explanation.
    error_type : str | None
        Stable error classification when the evaluator failed rather than
        returned a verdict; ``"timeout"`` for an elapsed timeout.
    """

    evaluator: str
    verdict: QualityVerdict
    summary: str | None = None
    error_type: str | None = None


class QualityEvaluatorPort(typ.Protocol):
    """One QA evaluator that judges a generated draft."""

    @property
    def name(self) -> str:
        """The evaluator's stable slug."""

    async def evaluate(self, subject: EvaluationSubject) -> QualityEvaluation:
        """Judge the subject and return a verdict."""


def _validate_evaluator_set(
    evaluators: tuple[QualityEvaluatorPort, ...],
    timeout_seconds: float,
) -> None:
    """Reject evaluator sets whose names or timeout would corrupt reporting."""
    if timeout_seconds <= 0:
        msg = "evaluator_timeout_seconds must be positive."
        raise ValueError(msg)
    names = [evaluator.name for evaluator in evaluators]
    if any(not name.strip() for name in names):
        msg = "every evaluator name must be a non-empty slug."
        raise ValueError(msg)
    if len(set(names)) != len(names):
        msg = "evaluator names must be unique."
        raise ValueError(msg)


@dc.dataclass(frozen=True, slots=True)
class QualityEvaluatorSet:
    """Configured evaluators and the timeout applied to each.

    Attributes
    ----------
    evaluators : tuple[QualityEvaluatorPort, ...]
        Evaluators to run for a QA-gated draft. An empty tuple means this
        deployment cannot evaluate anything.
    evaluator_timeout_seconds : float
        Per-evaluator timeout. Defaults to two minutes.

    Raises
    ------
    ValueError
        If the timeout is not positive, or an evaluator name is blank or
        duplicated.
    """

    evaluators: tuple[QualityEvaluatorPort, ...]
    evaluator_timeout_seconds: float = 120.0

    def __post_init__(self) -> None:
        """Validate evaluator naming and the timeout."""
        _validate_evaluator_set(self.evaluators, self.evaluator_timeout_seconds)

    def accepted_quality_modes(self) -> frozenset[QualityMode]:
        """Return the quality modes this deployment can execute.

        ``draft_without_qa`` is always accepted. ``qa_gated`` is accepted only
        when at least one evaluator is configured, so a request can never spend
        inference on a branch that must escalate for lack of evaluators.

        Returns
        -------
        frozenset[QualityMode]
            The quality modes this deployment can execute.
        """
        modes = {QualityMode.DRAFT_WITHOUT_QA}
        if self.evaluators:
            modes.add(QualityMode.QA_GATED)
        return frozenset(modes)


@dc.dataclass(frozen=True, slots=True)
class ContentGenerationRequest:
    """Input to one content-generation graph run.

    Attributes
    ----------
    run_id : uuid.UUID
        Generation run being executed.
    quality_mode : QualityMode
        Requested QA policy, which selects the graph branch.
    """

    run_id: uuid.UUID
    quality_mode: QualityMode


class ContentGenerationSteps(typ.Protocol):
    """Launcher-supplied I/O steps for one run.

    Every method executes inside the run's own launcher task. Implementations
    are the single writer of that run's events and status.
    """

    async def initialize(self) -> None:
        """Claim and hydrate the run, or return unchanged if it was lost."""

    async def generate_draft(self) -> None:
        """Generate the draft and record its generation event."""

    async def begin_evaluation(self, evaluator_names: tuple[str, ...]) -> None:
        """Record that evaluation started, naming the evaluators."""

    def evaluation_subject(self) -> EvaluationSubject:
        """Return the generated draft as an evaluation subject."""

    async def complete_with_draft(
        self,
        qa_status: QaStatus,
        evaluations: tuple[QualityEvaluation, ...],
    ) -> None:
        """Persist the draft and record the successful terminal."""

    async def escalate(
        self,
        verdict: QualityVerdict,
        evaluations: tuple[QualityEvaluation, ...],
    ) -> None:
        """Record the escalated terminal without persisting TEI."""


class ContentGenerationGraphPort(typ.Protocol):
    """Executable content-generation graph."""

    def accepted_quality_modes(self) -> frozenset[QualityMode]:
        """Return the quality modes this deployment can execute."""

    async def run(
        self,
        request: ContentGenerationRequest,
        *,
        steps: ContentGenerationSteps,
    ) -> GenerationTerminal:
        """Execute the run and return the terminal it reached."""


class QualityEvaluationUnavailableError(RuntimeError):
    """Raised when a QA-gated run has no configured evaluators."""


class ContentGenerationGraphError(RuntimeError):
    """Raised when a graph run ends without a terminal its branch owns."""
