"""Unit tests for the Pedante projection onto durable QA artefacts.

Discharges the deterministic half of ``INV-COMPLIANCE-BLOCKING`` and
``INV-MAPPING-FIDELITY``. Their generative statements live in
``tests/test_qa_artefact_recording_properties.py``; these cases pin the
compliance policy, the finding projection, and the provider metadata that the
generators are not guaranteed to draw.

The Chrono and failure outcomes are covered by
``tests/test_qa_artefact_recording_non_pedante.py``, and the idempotency key by
``tests/test_qa_artefact_idempotency_key.py``.
"""

import dataclasses as dc

import pytest

from episodic.canonical.qa_artefact_compliance import compliance_status_for_pedante
from episodic.canonical.qa_artefact_pedante import evaluation_from_pedante
from episodic.canonical.qa_artefact_recording import QaEvaluationTarget
from episodic.canonical.qa_artefacts import (
    MAX_SUMMARY_CHARS,
    QA_ARTEFACT_SCHEMA_VERSION,
    QA_COMPLIANCE_POLICY_VERSION,
    QaComplianceStatus,
    QaEvaluation,
    QaEvaluator,
    QaFindingSeverity,
)
from episodic.qa.pedante.types import (
    PEDANTE_CONTRACT_VERSION,
    ClaimKind,
    FindingSeverity,
    PedanteFinding,
    SupportLevel,
)
from tests.fixtures.qa_artefact_recording_builders import (
    EPISODE_ID,
    EVALUATED_AT,
    EVALUATION_ID,
    GENERATION_RUN_ID,
    TEI_CONTENT_HASH,
    identifier_sequence,
    pedante_finding,
    pedante_result,
)

_TARGET = QaEvaluationTarget(
    episode_id=EPISODE_ID,
    tei_content_hash=TEI_CONTENT_HASH,
    evaluated_at=EVALUATED_AT,
    generation_run_id=GENERATION_RUN_ID,
)
_DEFAULT_TARGET = QaEvaluationTarget(
    episode_id=EPISODE_ID,
    tei_content_hash=TEI_CONTENT_HASH,
    evaluated_at=EVALUATED_AT,
)


def _pedante_evaluation(*findings: PedanteFinding) -> QaEvaluation:
    """Map the supplied Pedante findings with deterministic identifiers.

    Each call gets its own identifier sequence, so the evaluation keeps the
    shared identifier while every finding still takes a distinct one.

    Returns
    -------
    QaEvaluation
        The mapped evaluation, carrying the shared evaluation identifier.
    """
    target = dc.replace(_TARGET, uuid_factory=identifier_sequence())
    return evaluation_from_pedante(pedante_result(*findings), target=target)


def test_records_pedante_result() -> None:
    """A Pedante result maps to one complete, persistable artefact."""
    blocking = pedante_finding(
        claim_id="claim-1",
        claim_text="The archive holds the earliest recording.",
        claim_kind=ClaimKind.DIRECT_QUOTE,
        support_level=SupportLevel.FABRICATED_CLAIM,
        severity=FindingSeverity.CRITICAL,
        summary="No cited source contains this quotation.",
        remediation="Remove or re-source the quotation.",
        cited_source_ids=("src-1", "src-2"),
    )
    supported = pedante_finding(
        claim_id="claim-2",
        claim_text="The collection was catalogued in 1974.",
        claim_kind=ClaimKind.INFERENCE,
        support_level=SupportLevel.INFERENCE_DIRECTLY_SUPPORTED,
        severity=FindingSeverity.LOW,
        summary="The inference follows from the catalogue entry.",
        remediation="No change required.",
        cited_source_ids=(),
    )

    evaluation = _pedante_evaluation(blocking, supported)

    assert isinstance(evaluation, QaEvaluation), (
        "the mapping should return a persistable evaluation"
    )
    assert evaluation.summary_record.id == EVALUATION_ID, (
        "the mapping should use the supplied identifier factory"
    )
    assert evaluation.summary_record.episode_id == EPISODE_ID, (
        "the evaluation should belong to the supplied episode"
    )
    assert evaluation.summary_record.evaluator is QaEvaluator.PEDANTE, (
        "a Pedante result should map to the Pedante evaluator"
    )
    assert evaluation.summary_record.evaluator_version == PEDANTE_CONTRACT_VERSION, (
        "the evaluation should record the Pedante contract version"
    )
    assert evaluation.summary_record.artefact_schema_version == (
        QA_ARTEFACT_SCHEMA_VERSION
    ), "the evaluation should record the current payload schema version"
    assert evaluation.summary_record.compliance_policy_version == (
        QA_COMPLIANCE_POLICY_VERSION
    ), "the evaluation should record the policy version that produced the verdict"
    assert (
        evaluation.summary_record.compliance_status is QaComplianceStatus.NON_COMPLIANT
    ), "one blocking finding should make the evaluation non-compliant"
    assert evaluation.summary_record.generation_run_id == GENERATION_RUN_ID, (
        "the evaluation should correlate with the launcher run"
    )
    assert evaluation.summary_record.finding_count == 2, (
        "the recorded finding count should match the mapping"
    )
    assert evaluation.summary_record.summary == "Pedante review complete.", (
        "the evaluator summary should be carried through"
    )
    assert [finding.code for finding in evaluation.findings] == [
        "fabricated_claim",
        "inference_directly_supported",
    ], "the findings should keep their emitted order and support levels"


@pytest.mark.parametrize(
    ("support_level", "expected"),
    [
        (SupportLevel.FABRICATED_CLAIM, QaComplianceStatus.NON_COMPLIANT),
        (SupportLevel.CITATION_ABSENT, QaComplianceStatus.NON_COMPLIANT),
        (SupportLevel.ACCURATE_QUOTATION, QaComplianceStatus.COMPLIANT),
        (
            SupportLevel.INFERENCE_PLAUSIBLY_SUPPORTED,
            QaComplianceStatus.COMPLIANT,
        ),
    ],
)
def test_compliance_status_follows_the_blocking_support_levels(
    support_level: SupportLevel,
    expected: QaComplianceStatus,
) -> None:
    """The policy verdict is decided by the support level, not the severity."""
    result = pedante_result(
        pedante_finding(
            support_level=support_level,
            severity=FindingSeverity.CRITICAL,
        )
    )

    assert compliance_status_for_pedante(result) is expected, (
        f"support level {support_level.value} mapped to the wrong verdict"
    )


def test_compliance_status_is_compliant_for_an_empty_result() -> None:
    """An evaluator that reported no findings permits the episode to advance."""
    assert compliance_status_for_pedante(pedante_result()) is (
        QaComplianceStatus.COMPLIANT
    ), "an empty finding list should be compliant"


def test_pedante_contract_version_starts_at_one() -> None:
    """The contract whose shape ADR 001 fixes is its first stable version."""
    assert PEDANTE_CONTRACT_VERSION == "1", (
        "the first stable Pedante contract should be version 1"
    )


def test_pedante_finding_projection_carries_every_field() -> None:
    """Each Pedante finding field reaches its documented QA finding field."""
    pedante = pedante_finding(
        claim_id="claim-42",
        claim_text="Café — la façade du théâtre date de 1904.",
        claim_kind=ClaimKind.TRANSPLANTED_CLAIM,
        support_level=SupportLevel.MISINTERPRETED_CLAIM,
        severity=FindingSeverity.HIGH,
        summary="The claim relocates an assertion made about another city.",
        remediation="Attribute the assertion to its actual subject.",
        cited_source_ids=("src-a", "src-b", "src-c"),
    )

    (derived,) = _pedante_evaluation(pedante).findings

    assert derived.ordinal == 0, "the first finding should carry ordinal zero"
    assert derived.code == "misinterpreted_claim", (
        "the finding code should be the raw support level"
    )
    assert derived.subject_id == "claim-42", (
        "the subject identifier should be the claim identifier"
    )
    assert derived.subject_text == pedante.claim_text, (
        "the subject text should be the verbatim claim text"
    )
    assert derived.citations == ("src-a", "src-b", "src-c"), (
        "every cited source identifier should be carried"
    )
    assert derived.details == {"claim_kind": "transplanted_claim"}, (
        "the claim kind should be preserved in the details payload"
    )
    assert derived.severity is QaFindingSeverity.HIGH, (
        "the severity should map onto the shared taxonomy"
    )
    assert derived.summary == pedante.summary, (
        "the finding summary should be carried verbatim"
    )
    assert derived.remediation == pedante.remediation, (
        "the remediation guidance should be carried verbatim"
    )
    assert derived.is_blocking is True, (
        "the blocking flag should follow the support level"
    )


def test_pedante_findings_keep_their_emission_order() -> None:
    """Ordinals follow emission order, not severity or support level."""
    findings = (
        pedante_finding(claim_id="first", claim_text="First claim."),
        pedante_finding(
            claim_id="second",
            claim_text="Second claim.",
            support_level=SupportLevel.FABRICATED_CLAIM,
            severity=FindingSeverity.CRITICAL,
        ),
        pedante_finding(claim_id="third", claim_text="Third claim."),
    )

    evaluation = _pedante_evaluation(*findings)

    assert [finding.ordinal for finding in evaluation.findings] == [0, 1, 2], (
        "ordinals should be consecutive from zero"
    )
    assert [finding.subject_id for finding in evaluation.findings] == [
        "first",
        "second",
        "third",
    ], "the projection reordered the findings"


def test_pedante_metadata_carries_the_provider_response() -> None:
    """Provider correlation fields are recorded without token usage."""
    result = pedante_result(model="anthropic/x", provider_response_id="resp-9")
    evaluation = evaluation_from_pedante(result, target=_DEFAULT_TARGET)

    assert evaluation.summary_record.evaluator_metadata == {
        "model": "anthropic/x",
        "provider_response_id": "resp-9",
        "finish_reason": "stop",
    }, "the provider metadata should be recorded in full"
    assert "usage" not in evaluation.summary_record.evaluator_metadata, (
        "token usage belongs to the cost ledger, not the artefact"
    )


def test_oversized_result_is_refused_rather_than_truncated() -> None:
    """A result beyond the stored bounds raises instead of being shortened."""
    result = pedante_result(summary="x" * (MAX_SUMMARY_CHARS + 1))

    with pytest.raises(ValueError, match="summary"):
        evaluation_from_pedante(result, target=_DEFAULT_TARGET)
