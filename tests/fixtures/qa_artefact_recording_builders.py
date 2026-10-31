"""Builders shared by the QA artefact recording test modules.

The deterministic suite and the property suite both need evaluator outcomes
that differ only where a case says so, so the identifiers and builders live
here rather than in either test module.
"""

import datetime as dt
import uuid

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


# pylint: disable-next=too-many-arguments,too-many-positional-arguments  # mirrors PedanteFinding's field surface
def pedante_finding(
    *,
    claim_id: str = "claim-1",
    claim_text: str = "The archive holds the earliest recording.",
    claim_kind: ClaimKind = ClaimKind.DIRECT_QUOTE,
    support_level: SupportLevel = SupportLevel.ACCURATE_QUOTATION,
    severity: FindingSeverity = FindingSeverity.LOW,
    summary: str = "The claim matches its cited passage.",
    remediation: str = "No change required.",
    cited_source_ids: tuple[str, ...] = ("src-1",),
) -> PedanteFinding:
    """Return a valid Pedante finding whose fields callers may override."""
    return PedanteFinding(
        claim_id=claim_id,
        claim_text=claim_text,
        claim_kind=claim_kind,
        support_level=support_level,
        severity=severity,
        summary=summary,
        remediation=remediation,
        cited_source_ids=cited_source_ids,
    )


def pedante_result(
    *findings: PedanteFinding,
    summary: str = "Pedante review complete.",
    model: str = "test-model",
    provider_response_id: str = "resp-1",
    finish_reason: str | None = "stop",
) -> PedanteEvaluationResult:
    """Return a Pedante result carrying the supplied findings."""
    return PedanteEvaluationResult(
        summary=summary,
        findings=findings,
        usage=LLMUsage(input_tokens=10, output_tokens=5, total_tokens=15),
        model=model,
        provider_response_id=provider_response_id,
        finish_reason=finish_reason,
    )


# pylint: disable-next=too-many-arguments,too-many-positional-arguments  # mirrors ChronoEstimatorMetadata's field surface
def chrono_estimate(
    *,
    estimated_seconds: int = 600,
    estimator_name: str = "chrono-naive-word-count",
    estimator_version: str = "1",
    input_character_count: int = 4200,
    spoken_word_count: int = 1500,
    words_per_minute: int = 150,
) -> ChronoRuntimeEstimate:
    """Return a valid Chrono estimate whose metadata callers may override."""
    return ChronoRuntimeEstimate(
        estimated_seconds=estimated_seconds,
        metadata=ChronoEstimatorMetadata(
            estimator_name=estimator_name,
            estimator_version=estimator_version,
            input_character_count=input_character_count,
            spoken_word_count=spoken_word_count,
            words_per_minute=words_per_minute,
        ),
    )
