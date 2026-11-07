"""Builders shared by the QA artefact domain test modules.

Both the model suite and the rubric-score suite need a valid artefact to
mutate, so the identifiers and builders live here rather than in either test
module.
"""

import dataclasses as dc
import datetime as dt
import uuid

from episodic.canonical.qa_artefacts import (
    QA_ARTEFACT_SCHEMA_VERSION,
    QA_COMPLIANCE_POLICY_VERSION,
    QaComplianceStatus,
    QaEvaluationSummary,
    QaEvaluator,
    QaFinding,
    QaFindingSeverity,
)
from episodic.qa.pedante.types import SupportLevel

# Authored from the Pedante taxonomy and the recorded compliance policy. It is
# deliberately not derived from the production `_BLOCKING_SUPPORT_LEVELS`; the
# exact-equality test in `tests/test_qa_artefact_domain.py` turns the pair into
# a transcription check, and the recording properties use this set as their
# oracle so a wrong production set cannot satisfy them.
DOCUMENTED_BLOCKING_LEVELS = frozenset({
    SupportLevel.CITATION_ABSENT,
    SupportLevel.MISQUOTATION,
    SupportLevel.MISINTERPRETED_CLAIM,
    SupportLevel.FABRICATED_CLAIM,
    SupportLevel.INFERENCE_NOT_SUPPORTED,
    SupportLevel.INACCURATE_REINTERPRETATION,
    SupportLevel.INFERENCE_SUPPORTED_WITH_IRRELEVANT_SOURCES,
    SupportLevel.CONTRADICTORY_CLAIMS_IN_DOCUMENT,
})

EPISODE_ID = uuid.UUID("0192f9d0-0000-7000-8000-00000000e901")
EVALUATION_ID = uuid.UUID("0192f9d0-0000-7000-8000-00000000e902")
FINDING_ID = uuid.UUID("0192f9d0-0000-7000-8000-00000000e903")
OTHER_FINDING_ID = uuid.UUID("0192f9d0-0000-7000-8000-00000000e904")
OTHER_EVALUATION_ID = uuid.UUID("0192f9d0-0000-7000-8000-00000000e905")
EVALUATED_AT = dt.datetime(2026, 10, 29, 12, 0, 0, tzinfo=dt.UTC)


_DEFAULT_FINDING = QaFinding(
    id=FINDING_ID,
    evaluation_id=EVALUATION_ID,
    ordinal=0,
    severity=QaFindingSeverity.LOW,
    code="citation_absent",
    summary="Claim is unsupported.",
)


def finding(**overrides: object) -> QaFinding:
    """Return a valid finding with model fields overridden by name.

    ``finding_id`` overrides the model's ``id`` field, and ``details=None``
    selects the default empty mapping.

    Parameters
    ----------
    **overrides
        ``QaFinding`` field names whose values replace the defaults.

    Returns
    -------
    QaFinding
        A new finding built from the defaults and the overrides.
    """
    changes = dict(overrides)
    if "finding_id" in changes:
        changes["id"] = changes.pop("finding_id")
    if changes.get("details") is None:
        changes.pop("details", None)
    return dc.replace(_DEFAULT_FINDING, **changes)


_DEFAULT_SUMMARY = QaEvaluationSummary(
    id=EVALUATION_ID,
    episode_id=EPISODE_ID,
    evaluator=QaEvaluator.PEDANTE,
    evaluator_version="pedante-1.0.0",
    artefact_schema_version=QA_ARTEFACT_SCHEMA_VERSION,
    compliance_policy_version=QA_COMPLIANCE_POLICY_VERSION,
    compliance_status=QaComplianceStatus.COMPLIANT,
    evaluated_at=EVALUATED_AT,
    idempotency_key="pedante:episode:1",
    finding_count=0,
)


def summary(**overrides: object) -> QaEvaluationSummary:
    """Return a valid summary with model fields overridden by name.

    ``evaluation_id`` overrides the model's ``id`` field, and
    ``evaluator_metadata=None`` selects the default empty mapping.

    Parameters
    ----------
    **overrides
        ``QaEvaluationSummary`` field names whose values replace the defaults.

    Returns
    -------
    QaEvaluationSummary
        A new summary built from the defaults and the overrides.
    """
    changes = dict(overrides)
    if "evaluation_id" in changes:
        changes["id"] = changes.pop("evaluation_id")
    if changes.get("evaluator_metadata") is None:
        changes.pop("evaluator_metadata", None)
    return dc.replace(_DEFAULT_SUMMARY, **changes)
