"""Quality-assurance evaluator contracts.

The LangGraph adapters live in :mod:`episodic.qa.langgraph` and
:mod:`episodic.qa.chrono_langgraph` and are deliberately **not** re-exported
here: a submodule import executes this module first, so a re-export would make
every evaluator-contract import load the orchestration stack.
"""

from episodic.observability import MonotonicClockPort

from .chrono import (
    ChronoEstimatorConfig,
    ChronoEstimatorMetadata,
    ChronoEvaluationRequest,
    ChronoMetricsPort,
    ChronoRuntimeEstimate,
    ChronoRuntimeEstimator,
)
from .pedante import (
    ClaimKind,
    FindingSeverity,
    PedanteEvaluationRequest,
    PedanteEvaluationResult,
    PedanteEvaluator,
    PedanteEvaluatorConfig,
    PedanteFinding,
    PedanteResponseFormatError,
    PedanteSourcePacket,
    SupportLevel,
)

__all__: list[str] = [
    "ChronoEstimatorConfig",
    "ChronoEstimatorMetadata",
    "ChronoEvaluationRequest",
    "ChronoMetricsPort",
    "ChronoRuntimeEstimate",
    "ChronoRuntimeEstimator",
    "ClaimKind",
    "FindingSeverity",
    "MonotonicClockPort",
    "PedanteEvaluationRequest",
    "PedanteEvaluationResult",
    "PedanteEvaluator",
    "PedanteEvaluatorConfig",
    "PedanteFinding",
    "PedanteResponseFormatError",
    "PedanteSourcePacket",
    "SupportLevel",
]
