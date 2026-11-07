"""Unit tests for the QA-artefact API serializers.

``LEM-SERIALIZATION-STABLE`` pins four variants: a fully populated summary, a
minimal summary, a detail payload with findings, and the JSON encoding of a
decimal rubric score. The last one exists because Falcon cannot encode a
``decimal.Decimal`` and the serializer must convert it to a JSON number.
"""

import decimal
import json
import typing as typ
import uuid

import pytest

from episodic.api.serializers import (
    serialize_qa_evaluation,
    serialize_qa_evaluation_summary,
    serialize_qa_finding,
)
from episodic.canonical.qa_artefacts import (
    QaComplianceStatus,
    QaEvaluation,
    QaEvaluationSummary,
    QaEvaluator,
    QaFinding,
    QaFindingSeverity,
)
from tests.fixtures.qa_artefact_builders import (
    EPISODE_ID,
    EVALUATED_AT,
    EVALUATION_ID,
    FINDING_ID,
    OTHER_FINDING_ID,
    finding,
    summary,
)
from tests.fixtures.qa_artefact_recording_builders import GENERATION_RUN_ID
from tests.snapshot_redaction import redact_snapshot_uuids

if typ.TYPE_CHECKING:
    from syrupy.assertion import SnapshotAssertion

_THIRD_FINDING_ID = uuid.UUID("0192f9d0-0000-7000-8000-00000000e907")
_DECIMAL_SCORE = decimal.Decimal("0.1234")


def _populated_summary() -> QaEvaluationSummary:
    """Return a summary with every optional field populated."""
    return summary(
        evaluator=QaEvaluator.CHRONO,
        evaluator_version="1",
        compliance_status=QaComplianceStatus.NOT_APPLICABLE,
        evaluated_at=EVALUATED_AT,
        finding_count=0,
        summary="Estimated runtime.",
        rubric_score=decimal.Decimal("0.8750"),
        runtime_estimate_seconds=600,
        evaluator_metadata={
            "estimator_name": "chrono-naive-word-count",
            "estimator_version": "1",
            "words_per_minute": 150,
        },
        generation_run_id=GENERATION_RUN_ID,
    )


def _findings() -> tuple[QaFinding, ...]:
    """Return three ordered findings with distinct detail payloads."""
    return (
        finding(
            finding_id=FINDING_ID,
            evaluation_id=EVALUATION_ID,
            ordinal=0,
            severity=QaFindingSeverity.HIGH,
            code="citation_absent",
            summary="The claim has no citation.",
            remediation="Cite the archive catalogue.",
            subject_id="claim-1",
            subject_text="The archive holds three reels.",
            is_blocking=True,
            citations=(),
            details={"claim_kind": "direct_quote"},
        ),
        finding(
            finding_id=OTHER_FINDING_ID,
            evaluation_id=EVALUATION_ID,
            ordinal=1,
            severity=QaFindingSeverity.LOW,
            code="accurate_quotation",
            summary="The quotation matches.",
            remediation="No change required.",
            subject_id="claim-2",
            subject_text="The reels date from 1954.",
            citations=("src-1", "src-2"),
            details={"claim_kind": "direct_quote"},
        ),
        finding(
            finding_id=_THIRD_FINDING_ID,
            evaluation_id=EVALUATION_ID,
            ordinal=2,
            severity=QaFindingSeverity.MEDIUM,
            code="accurate_restatement",
            summary="The restatement is faithful.",
            remediation="No change required.",
            subject_id="claim-3",
            subject_text="The session was recorded in winter.",
            citations=("src-3",),
            details={"claim_kind": "transplanted_claim"},
        ),
    )


def _detail_evaluation(*, rubric_score: decimal.Decimal | None) -> QaEvaluation:
    """Return a detail evaluation carrying the shared findings."""
    findings = _findings()
    return QaEvaluation(
        summary_record=summary(
            episode_id=EPISODE_ID,
            evaluator=QaEvaluator.PEDANTE,
            compliance_status=QaComplianceStatus.NON_COMPLIANT,
            finding_count=len(findings),
            summary="One claim lacks source support.",
            rubric_score=rubric_score,
            evaluator_metadata={"model": "pedante-test-model"},
            generation_run_id=GENERATION_RUN_ID,
        ),
        findings=findings,
    )


def test_fully_populated_summary_matches_snapshot(
    snapshot: SnapshotAssertion,
) -> None:
    """A summary with every optional field serializes to the pinned shape."""
    payload = serialize_qa_evaluation_summary(_populated_summary())

    assert redact_snapshot_uuids(payload) == snapshot, (
        "the populated summary representation changed"
    )


def test_minimal_summary_matches_snapshot(snapshot: SnapshotAssertion) -> None:
    """A summary without optional fields keeps the same keys, nulled."""
    payload = serialize_qa_evaluation_summary(summary())

    assert redact_snapshot_uuids(payload) == snapshot, (
        "the minimal summary representation changed"
    )


def test_detail_with_findings_matches_snapshot(snapshot: SnapshotAssertion) -> None:
    """A detail payload is the summary plus its ordered findings."""
    payload = serialize_qa_evaluation(_detail_evaluation(rubric_score=None))

    assert redact_snapshot_uuids(payload) == snapshot, (
        "the detail representation changed"
    )


def test_detail_is_a_superset_of_the_summary() -> None:
    """Every summary key survives in the detail representation."""
    evaluation = _detail_evaluation(rubric_score=None)

    detail = serialize_qa_evaluation(evaluation)
    listing = serialize_qa_evaluation_summary(evaluation.summary_record)

    assert {key: detail[key] for key in listing} == listing, (
        "the detail payload does not extend the summary payload"
    )
    findings = typ.cast("list[dict[str, object]]", detail["findings"])
    assert findings[0]["citations"] == [], findings[0]
    assert findings[1]["citations"] == ["src-1", "src-2"], findings[1]
    assert findings[0]["details"] == {"claim_kind": "direct_quote"}, findings[0]
    assert findings[0]["is_blocking"] is True, findings[0]


def test_finding_serializer_carries_every_field(
    snapshot: SnapshotAssertion,
) -> None:
    """The finding serializer exposes the documented field set."""
    payload = serialize_qa_finding(_findings()[1])

    encoded = json.dumps(redact_snapshot_uuids(payload), indent=2, sort_keys=True)
    assert encoded == snapshot, "the finding payload changed"


def test_rubric_score_encodes_as_a_json_number(
    snapshot: SnapshotAssertion,
) -> None:
    """A decimal rubric score reaches JSON as a number, not a string."""
    payload = serialize_qa_evaluation(_detail_evaluation(rubric_score=_DECIMAL_SCORE))

    assert isinstance(payload["rubric_score"], float), payload["rubric_score"]
    encoded = json.dumps(redact_snapshot_uuids(payload), indent=2, sort_keys=True)
    assert encoded == snapshot, "the JSON encoding of the detail payload changed"
    assert json.loads(encoded)["rubric_score"] == pytest.approx(0.1234), encoded
