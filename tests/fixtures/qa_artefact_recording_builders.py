"""Builders shared by the QA artefact recording test modules.

The deterministic suite and the property suite both need evaluator outcomes
that differ only where a case says so, so the identifiers and builders live
here rather than in either test module.
"""

import dataclasses as dc
import datetime as dt
import itertools
import typing as typ
import uuid

if typ.TYPE_CHECKING:
    import collections.abc as cabc

from episodic.llm.ports import LLMUsage
from episodic.qa.chrono import ChronoEstimatorMetadata, ChronoRuntimeEstimate
from episodic.qa.pedante.types import (
    ClaimKind,
    FindingSeverity,
    PedanteEvaluationResult,
    PedanteFinding,
    SupportLevel,
)

EPISODE_ID = uuid.UUID("0192f9d0-0000-7000-8000-00000000e911")
EVALUATION_ID = uuid.UUID("0192f9d0-0000-7000-8000-00000000e912")
GENERATION_RUN_ID = uuid.UUID("0192f9d0-0000-7000-8000-00000000e913")
EVALUATED_AT = dt.datetime(2026, 10, 31, 9, 0, tzinfo=dt.UTC)
TEI_CONTENT_HASH = "sha256:0f1e2d3c4b5a69788796a5b4c3d2e1f0"

_DEFAULT_PEDANTE_FINDING = PedanteFinding(
    claim_id="claim-1",
    claim_text="The archive holds the earliest recording.",
    claim_kind=ClaimKind.DIRECT_QUOTE,
    support_level=SupportLevel.ACCURATE_QUOTATION,
    severity=FindingSeverity.LOW,
    summary="The claim matches its cited passage.",
    remediation="No change required.",
    cited_source_ids=("src-1",),
)

_DEFAULT_PEDANTE_RESULT = PedanteEvaluationResult(
    summary="Pedante review complete.",
    findings=(),
    usage=LLMUsage(input_tokens=10, output_tokens=5, total_tokens=15),
    model="test-model",
    provider_response_id="resp-1",
    finish_reason="stop",
)

_DEFAULT_CHRONO_METADATA = ChronoEstimatorMetadata(
    estimator_name="chrono-naive-word-count",
    estimator_version="1",
    input_character_count=4200,
    spoken_word_count=1500,
    words_per_minute=150,
)


def identifier_sequence(
    first: uuid.UUID = EVALUATION_ID,
) -> cabc.Callable[[], uuid.UUID]:
    """Build a deterministic identifier factory for the projection doubles.

    The production contract is that the factory never repeats itself: an
    evaluation and each of its findings take one identifier apiece. A double
    that always returned the same value would give every finding the
    evaluation's identifier and trip the distinctness check, so the first call
    yields *first* and later calls derive a deterministic identifier from it,
    which also keeps two sequences started from different evaluations apart.

    Returns
    -------
    cabc.Callable[[], uuid.UUID]
        A zero-argument factory whose first result is *first*.
    """
    issued = itertools.count()

    def next_identifier() -> uuid.UUID:
        """Return the next identifier in the sequence.

        Returns
        -------
        uuid.UUID
            The first evaluation identifier, then deterministic derived ones.
        """
        ordinal = next(issued)
        if ordinal == 0:
            return first
        return uuid.uuid5(first, f"identifier-{ordinal}")

    return next_identifier


def pedante_finding(**overrides: object) -> PedanteFinding:
    """Return a valid Pedante finding whose fields callers may override."""
    return dc.replace(_DEFAULT_PEDANTE_FINDING, **overrides)


def pedante_result(
    *findings: PedanteFinding,
    **overrides: object,
) -> PedanteEvaluationResult:
    """Return a Pedante result carrying the supplied findings."""
    return dc.replace(_DEFAULT_PEDANTE_RESULT, findings=findings, **overrides)


def chrono_metadata(**overrides: object) -> ChronoEstimatorMetadata:
    """Return valid estimator metadata whose fields callers may override."""
    return dc.replace(_DEFAULT_CHRONO_METADATA, **overrides)


def chrono_estimate(
    *,
    estimated_seconds: int = 600,
    metadata: ChronoEstimatorMetadata | None = None,
) -> ChronoRuntimeEstimate:
    """Return a Chrono estimate, defaulting its metadata."""
    return ChronoRuntimeEstimate(
        estimated_seconds=estimated_seconds,
        metadata=_DEFAULT_CHRONO_METADATA if metadata is None else metadata,
    )
