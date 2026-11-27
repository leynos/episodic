"""QA evaluation observation: per-evaluator latency and run-scoped logs.

The graph records one latency observation per evaluator, labelled by
evaluator and verdict, whatever the outcome: a verdict, a fault, or a
timeout. Every evaluator log line names the run, so an operator can join the
line to the run that produced it.
"""

import asyncio
import typing as typ
import uuid

import pytest

if typ.TYPE_CHECKING:
    import collections.abc as cabc

from episodic.canonical.generation_graph_ports import (
    ContentGenerationRequest,
    EvaluationSubject,
    QualityEvaluation,
    QualityEvaluatorSet,
)
from episodic.canonical.generation_quality import QualityMode
from episodic.canonical.generation_routing import GenerationTerminal, QualityVerdict
from episodic.orchestration.content_generation import (
    LangGraphContentGenerationGraph,
)
from tests._content_graph_fakes import RecordingSteps
from tests.generation_run_launcher_observation_support import RecordingMetrics

_RUN_ID = uuid.UUID("018fdcf0-0000-7000-8000-000000000001")
_LATENCY = "generation_run_qa_evaluation_latency_ms"
_NODE_LOGGER = "episodic.orchestration._content_graph_nodes"
_SHORT_TIMEOUT_SECONDS = 0.01


class _Evaluator:
    """Evaluator that returns a fixed verdict after an optional delay."""

    def __init__(
        self,
        name: str,
        verdict: QualityVerdict,
        *,
        delay_seconds: float = 0.0,
    ) -> None:
        """Store the name, verdict and delay."""
        self._name = name
        self._verdict = verdict
        self._delay_seconds = delay_seconds

    @property
    def name(self) -> str:
        """The evaluator's stable slug."""
        return self._name

    async def evaluate(self, subject: EvaluationSubject) -> QualityEvaluation:
        """Wait the configured delay, then return the fixed verdict."""
        _ = subject
        if self._delay_seconds:
            await asyncio.sleep(self._delay_seconds)
        return QualityEvaluation(self._name, self._verdict)


class _FaultingEvaluator:
    """Evaluator whose adapter raises, producing an inconclusive result."""

    @property
    def name(self) -> str:
        """The evaluator's stable slug."""
        return "faulting"

    async def evaluate(self, subject: EvaluationSubject) -> QualityEvaluation:
        """Raise an adapter fault."""
        _ = subject
        msg = "adapter unavailable"
        raise RuntimeError(msg)


def _graph(
    evaluator: object,
    metrics: RecordingMetrics,
) -> LangGraphContentGenerationGraph:
    """Build a QA-gated graph over one evaluator and the recording metrics."""
    return LangGraphContentGenerationGraph(
        QualityEvaluatorSet(
            (typ.cast("typ.Any", evaluator),),
            evaluator_timeout_seconds=_SHORT_TIMEOUT_SECONDS,
        ),
        metrics=metrics,
    )


async def _run(graph: LangGraphContentGenerationGraph) -> GenerationTerminal:
    """Run one QA-gated request through the graph."""
    return await graph.run(
        ContentGenerationRequest(
            run_id=_RUN_ID,
            quality_mode=QualityMode.QA_GATED,
        ),
        steps=RecordingSteps(),
    )


def _latency_labels(metrics: RecordingMetrics) -> list[dict[str, str]]:
    """Return the labels of every QA evaluation latency observation."""
    return [
        observation.labels
        for observation in metrics.observations
        if observation.kind == "latency_ms" and observation.name == _LATENCY
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("evaluator", "expected_verdict", "expected_terminal"),
    [
        (
            _Evaluator("passing", QualityVerdict.PASSED),
            QualityVerdict.PASSED,
            GenerationTerminal.QA_PASSED_DRAFT_PERSISTED,
        ),
        (
            _Evaluator("failing", QualityVerdict.FAILED),
            QualityVerdict.FAILED,
            GenerationTerminal.QA_ESCALATED,
        ),
        (
            _Evaluator(
                "timing-out",
                QualityVerdict.PASSED,
                delay_seconds=1.0,
            ),
            QualityVerdict.INCONCLUSIVE,
            GenerationTerminal.QA_ESCALATED,
        ),
        (
            _FaultingEvaluator(),
            QualityVerdict.INCONCLUSIVE,
            GenerationTerminal.QA_ESCALATED,
        ),
    ],
    ids=["passing", "failing", "timed-out", "faulting"],
)
async def test_every_evaluator_outcome_records_its_latency(
    evaluator: object,
    expected_verdict: QualityVerdict,
    expected_terminal: GenerationTerminal,
) -> None:
    """Each evaluator records one latency, labelled by evaluator and verdict."""
    metrics = RecordingMetrics()

    terminal = await _run(_graph(evaluator, metrics))

    assert terminal is expected_terminal, terminal
    assert _latency_labels(metrics) == [
        {
            "evaluator": typ.cast("typ.Any", evaluator).name,
            "verdict": expected_verdict.value,
        }
    ], metrics.observations


class _RecordCollector:
    """Capture femtologging records emitted by one named logger."""

    def __init__(self) -> None:
        """Start with no records."""
        self.messages: list[str] = []

    def handle(self, logger_name: str, level: str, message: str) -> None:
        """Accept the basic handler protocol and keep the message."""
        _ = (logger_name, level)
        self.messages.append(message)

    def handle_record(self, record: dict[str, object]) -> None:
        """Keep the formatted message from a structured record."""
        self.messages.append(str(record.get("message", "")))

    def flush(self) -> bool:
        """Report that nothing is buffered."""
        return True


def _wait_for_timeout_line(
    collector: _RecordCollector,
    *,
    timeout_seconds: float = 2.0,
) -> list[str]:
    """Wait for asynchronous delivery and return the timeout lines."""
    import time

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        lines = [
            message
            for message in collector.messages
            if "content_generation.evaluator_timeout" in message
        ]
        if lines:
            return lines
        time.sleep(0.01)
    return []


@pytest.fixture
def node_log_collector() -> cabc.Generator[_RecordCollector]:
    """Attach a collector to the graph-node logger for one test.

    The node module resolves its logger handle at import time, so this must
    not reset femtologging's manager: a reset would discard that handle and
    the records would never reach the collector. Handlers are cleared again at
    teardown instead.

    Yields
    ------
    _RecordCollector
        The collector attached to the graph-node logger.
    """
    import femtologging

    backend = femtologging.get_logger(_NODE_LOGGER)
    backend.clear_handlers()
    backend.set_propagate(False)
    collector = _RecordCollector()
    backend.add_handler(collector)
    yield collector
    backend.clear_handlers()
    backend.set_propagate(True)


@pytest.mark.asyncio
async def test_evaluator_log_lines_name_the_run(
    node_log_collector: _RecordCollector,
) -> None:
    """A timeout log line carries the run identifier and the evaluator."""
    metrics = RecordingMetrics()
    slow = _Evaluator("slow", QualityVerdict.PASSED, delay_seconds=1.0)
    graph = _graph(slow, metrics)

    await _run(graph)

    timeout_lines = _wait_for_timeout_line(node_log_collector)
    assert timeout_lines, node_log_collector.messages
    assert all(f"run_id={_RUN_ID}" in message for message in timeout_lines), (
        timeout_lines
    )
    assert all("evaluator=slow" in message for message in timeout_lines), timeout_lines
