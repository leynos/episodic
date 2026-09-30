"""Pedante factuality and accuracy evaluator.

This package implements Pedante, an LLM-backed evaluator that checks whether
claims in TEI P5 podcast scripts are accurately supported by their cited source
material.

Main entry points:

- ``PedanteEvaluator``: The primary evaluator class that orchestrates LLM-based
  factuality assessment. Call ``await evaluator.evaluate(request)`` to analyze a
  script and receive structured findings.
- ``PedanteEvaluationRequest``: Input contract containing the TEI XML script and
  source packets.
- ``PedanteEvaluationResult``: Output contract providing a summary, typed
  findings, LLM usage metadata, and a ``requires_revision`` flag.

The former single module was split under
https://github.com/leynos/episodic/issues/92 into evaluator orchestration,
DTO/enum contracts, and strict JSON parsing helpers.
"""

from .evaluator import PedanteEvaluator
from .types import (
    ClaimKind,
    FindingSeverity,
    PedanteEvaluationRequest,
    PedanteEvaluationResult,
    PedanteEvaluatorConfig,
    PedanteFinding,
    PedanteResponseFormatError,
    PedanteSourcePacket,
    SupportLevel,
)

__all__ = (
    "ClaimKind",
    "FindingSeverity",
    "PedanteEvaluationRequest",
    "PedanteEvaluationResult",
    "PedanteEvaluator",
    "PedanteEvaluatorConfig",
    "PedanteFinding",
    "PedanteResponseFormatError",
    "PedanteSourcePacket",
    "SupportLevel",
)
