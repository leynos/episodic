"""Post-commit observations the run session reports and the launcher records.

The session decides *what happened* — a no-QA run was claimed, or a QA gate
reached a verdict after its terminal write committed. This unit decides what
that means for metrics, so the session carries no metric name or sink and the
launcher emits from one place once the graph has finished.
"""

import dataclasses as dc
import typing as typ

from episodic.canonical.generation_graph_ports import (  # ruff: ignore[typing-only-first-party-import]  # Dataclass annotations are evaluated at runtime.
    QualityEvaluation,
)
from episodic.canonical.generation_quality import (  # ruff: ignore[typing-only-first-party-import]  # Dataclass annotations are evaluated at runtime.
    QualityMode,
)
from episodic.generation.launcher_quality import record_qa_metrics

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from episodic.canonical.generation_routing import QualityVerdict
    from episodic.observability import ValueMetricsPort

_METRIC_QA_BYPASS = "generation_run_qa_bypass_total"


@dc.dataclass(frozen=True, slots=True)
class QaBypassed:
    """A claimed run whose quality mode skips evaluation."""

    quality_mode: QualityMode


@dc.dataclass(frozen=True, slots=True)
class QaConcluded:
    """A committed QA gate outcome and the evaluations behind it."""

    verdict: QualityVerdict
    evaluations: tuple[QualityEvaluation, ...]


type RunObservation = QaBypassed | QaConcluded


def record_run_observations(
    metrics: ValueMetricsPort,
    observations: cabc.Sequence[RunObservation],
) -> None:
    """Record every observation one run reported, after its writes committed.

    Parameters
    ----------
    metrics : ValueMetricsPort
        Sink for the QA bypass and gate counters.
    observations : cabc.Sequence[RunObservation]
        Observations accumulated by the run session, in occurrence order.
    """
    for observation in observations:
        match observation:
            case QaBypassed(quality_mode=quality_mode):
                metrics.increment_counter(
                    _METRIC_QA_BYPASS,
                    labels={"quality_mode": quality_mode.value},
                )
            case QaConcluded(verdict=verdict, evaluations=evaluations):
                record_qa_metrics(metrics, verdict, evaluations)


__all__ = [
    "QaBypassed",
    "QaConcluded",
    "RunObservation",
    "record_run_observations",
]
