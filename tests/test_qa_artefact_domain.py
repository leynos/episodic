"""Unit tests for the QA artefact domain model and its compliance policy.

Discharges the obligations the ExecPlan assigns to this module: ``INV-BLOCKING-
SET``, ``INV-ENUM-TAXONOMY``, the domain half of ``INV-TIMEZONE``, and every
``__post_init__`` rejection. The blocking set is written out here rather than
read from the production module, because ``INV-COMPLIANCE-BLOCKING`` inherits
the set from the code under test and cannot detect a wrong one on its own.
"""

import datetime as dt
import decimal
import typing as typ
import uuid

import pytest

from episodic.canonical.qa_artefacts import (
    MAX_CITATION_CHARS,
    MAX_CITATIONS,
    MAX_CODE_CHARS,
    MAX_FINDINGS_PER_EVALUATION,
    MAX_REMEDIATION_CHARS,
    MAX_SUBJECT_TEXT_CHARS,
    MAX_SUMMARY_CHARS,
    QA_ARTEFACT_SCHEMA_VERSION,
    QA_COMPLIANCE_POLICY_VERSION,
    QaComplianceStatus,
    QaEvaluation,
    QaEvaluationSummary,
    QaEvaluator,
    QaFinding,
    QaFindingSeverity,
)
from episodic.qa.pedante import ClaimKind, FindingSeverity, PedanteFinding, SupportLevel
from episodic.qa.pedante.types import _BLOCKING_SUPPORT_LEVELS

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from episodic.canonical.domain_enums import JsonMapping

_EPISODE_ID = uuid.UUID("0192f9d0-0000-7000-8000-00000000e901")
_EVALUATION_ID = uuid.UUID("0192f9d0-0000-7000-8000-00000000e902")
_FINDING_ID = uuid.UUID("0192f9d0-0000-7000-8000-00000000e903")
_EVALUATED_AT = dt.datetime(2026, 10, 29, 12, 0, 0, tzinfo=dt.UTC)

# Authored from the Pedante taxonomy and the recorded compliance policy. It is
# deliberately not derived from `_BLOCKING_SUPPORT_LEVELS`; the exact-equality
# test below turns the pair into a transcription check.
_DOCUMENTED_BLOCKING_LEVELS = frozenset({
    SupportLevel.CITATION_ABSENT,
    SupportLevel.MISQUOTATION,
    SupportLevel.MISINTERPRETED_CLAIM,
    SupportLevel.FABRICATED_CLAIM,
    SupportLevel.INFERENCE_NOT_SUPPORTED,
    SupportLevel.INACCURATE_REINTERPRETATION,
    SupportLevel.INFERENCE_SUPPORTED_WITH_IRRELEVANT_SOURCES,
    SupportLevel.CONTRADICTORY_CLAIMS_IN_DOCUMENT,
})

_DOCUMENTED_EVALUATORS = {
    "pedante",
    "bromide",
    "chiltern",
    "anthem",
    "caesura",
    "chrono",
}
_DOCUMENTED_COMPLIANCE_STATUSES = {
    "compliant",
    "non_compliant",
    "not_applicable",
    "errored",
}
_DOCUMENTED_FINDING_SEVERITIES = {"low", "medium", "high", "critical"}


def _pedante_finding(support_level: SupportLevel) -> PedanteFinding:
    return PedanteFinding(
        claim_id="claim-1",
        claim_text="The archive holds three reels.",
        claim_kind=ClaimKind.DIRECT_QUOTE,
        support_level=support_level,
        severity=FindingSeverity.MEDIUM,
        summary="Claim assessed.",
        remediation="Cite the archive catalogue.",
        cited_source_ids=("src-1",),
    )


# pylint: disable-next=too-many-arguments  # mirrors QaFinding's field surface
def _finding(
    *,
    ordinal: int = 0,
    severity: QaFindingSeverity = QaFindingSeverity.LOW,
    code: str = "citation_absent",
    summary: str = "Claim is unsupported.",
    remediation: str = "",
    subject_text: str = "",
    is_blocking: bool = False,
    citations: tuple[str, ...] = (),
    details: JsonMapping | None = None,
) -> QaFinding:
    return QaFinding(
        id=_FINDING_ID,
        evaluation_id=_EVALUATION_ID,
        ordinal=ordinal,
        severity=severity,
        code=code,
        summary=summary,
        remediation=remediation,
        subject_text=subject_text,
        is_blocking=is_blocking,
        citations=citations,
        details={} if details is None else details,
    )


# pylint: disable-next=too-many-arguments  # mirrors the summary's field surface
def _summary(
    *,
    evaluator: QaEvaluator = QaEvaluator.PEDANTE,
    evaluator_version: str = "pedante-1.0.0",
    compliance_status: QaComplianceStatus = QaComplianceStatus.COMPLIANT,
    evaluated_at: dt.datetime = _EVALUATED_AT,
    idempotency_key: str = "pedante:episode:1",
    finding_count: int = 0,
    summary: str = "",
    rubric_score: decimal.Decimal | None = None,
    runtime_estimate_seconds: int | None = None,
) -> QaEvaluationSummary:
    return QaEvaluationSummary(
        id=_EVALUATION_ID,
        episode_id=_EPISODE_ID,
        evaluator=evaluator,
        evaluator_version=evaluator_version,
        artefact_schema_version=QA_ARTEFACT_SCHEMA_VERSION,
        compliance_policy_version=QA_COMPLIANCE_POLICY_VERSION,
        compliance_status=compliance_status,
        evaluated_at=evaluated_at,
        idempotency_key=idempotency_key,
        finding_count=finding_count,
        summary=summary,
        rubric_score=rubric_score,
        runtime_estimate_seconds=runtime_estimate_seconds,
    )


# --- INV-BLOCKING-SET -------------------------------------------------------


@pytest.mark.parametrize("support_level", list(SupportLevel))
def test_blocking_flag_follows_the_documented_policy(
    support_level: SupportLevel,
) -> None:
    """Every taxonomy member blocks exactly when the policy says it does."""
    assert _pedante_finding(support_level).is_blocking is (
        support_level in _DOCUMENTED_BLOCKING_LEVELS
    ), f"{support_level.value} disagrees with the documented blocking policy"


def test_documented_blocking_set_matches_the_production_set() -> None:
    """The independently authored set has not drifted from production."""
    assert _DOCUMENTED_BLOCKING_LEVELS == _BLOCKING_SUPPORT_LEVELS, (
        "the test's independent blocking set and the production set have drifted"
    )
    assert len(_DOCUMENTED_BLOCKING_LEVELS) == 8, (
        "the documented blocking set changed size; re-check the policy"
    )


def test_documented_blocking_set_is_a_strict_subset_of_the_taxonomy() -> None:
    """A set equal to the taxonomy would make every finding blocking."""
    assert set(SupportLevel) > _DOCUMENTED_BLOCKING_LEVELS, (
        "a blocking set equal to the whole taxonomy would make every finding "
        "blocking and the membership test vacuous"
    )


# --- INV-ENUM-TAXONOMY ------------------------------------------------------


@pytest.mark.parametrize(
    ("enum_type", "expected"),
    [
        (QaEvaluator, _DOCUMENTED_EVALUATORS),
        (QaComplianceStatus, _DOCUMENTED_COMPLIANCE_STATUSES),
        (QaFindingSeverity, _DOCUMENTED_FINDING_SEVERITIES),
    ],
)
def test_enum_value_sets_match_the_documented_taxonomy(
    enum_type: type[QaEvaluator | QaComplianceStatus | QaFindingSeverity],
    expected: set[str],
) -> None:
    """Each stored vocabulary equals the documented one, member for member."""
    assert {member.value for member in enum_type} == expected, (
        f"{enum_type.__name__} drifted from the documented vocabulary"
    )


# --- INV-TIMEZONE, domain half ---------------------------------------------


def test_naive_evaluated_at_is_rejected() -> None:
    """A naive timestamp cannot be stored, because its instant is ambiguous."""
    with pytest.raises(ValueError, match="evaluated_at"):
        _summary(evaluated_at=_EVALUATED_AT.replace(tzinfo=None))


@pytest.mark.parametrize(
    "tz",
    [
        dt.UTC,
        dt.timezone(dt.timedelta(hours=5, minutes=30)),
        dt.timezone(dt.timedelta(hours=-8)),
    ],
)
def test_aware_evaluated_at_keeps_its_instant_and_offset(
    tz: dt.tzinfo,
) -> None:
    """Aware timestamps are stored as given, not normalized to UTC."""
    moment = dt.datetime(2026, 10, 29, 12, 0, 0, tzinfo=tz)

    stored = _summary(evaluated_at=moment).evaluated_at

    assert stored == moment, "the stored instant differs from the supplied one"
    assert stored.tzinfo is not None, "the stored timestamp lost its zone"
    assert stored.utcoffset() == tz.utcoffset(None), "the stored offset changed"


# --- summary rejections -----------------------------------------------------


@pytest.mark.parametrize(
    ("field_name", "build"),
    [
        ("runtime_estimate_seconds", lambda: _summary(runtime_estimate_seconds=-1)),
        ("evaluator_version", lambda: _summary(evaluator_version="")),
        ("evaluator_version", lambda: _summary(evaluator_version="   ")),
        ("idempotency_key", lambda: _summary(idempotency_key="")),
        ("summary", lambda: _summary(summary="x" * (MAX_SUMMARY_CHARS + 1))),
        ("rubric_score", lambda: _summary(rubric_score=decimal.Decimal("1.00006"))),
        ("rubric_score", lambda: _summary(rubric_score=decimal.Decimal("-0.00006"))),
    ],
)
def test_summary_rejects_invalid_field_values(
    field_name: str,
    build: cabc.Callable[[], QaEvaluationSummary],
) -> None:
    """Each documented bound rejects a value just past it."""
    with pytest.raises((TypeError, ValueError), match=field_name):
        build()


@pytest.mark.parametrize(
    "rubric_score",
    [
        decimal.Decimal(0),
        decimal.Decimal(1),
        decimal.Decimal("0.5"),
        decimal.Decimal("1.00004"),
        decimal.Decimal("-0.00004"),
    ],
)
def test_rubric_score_accepts_values_inside_the_unit_interval(
    rubric_score: decimal.Decimal,
) -> None:
    """Scores inside the interval, or rounding into it, are stored as given."""
    assert _summary(rubric_score=rubric_score).rubric_score == rubric_score, (
        "a score inside the unit interval was altered in construction"
    )


# --- finding rejections -----------------------------------------------------


def test_finding_rejects_an_overlong_code() -> None:
    """A finding code longer than the bound is model output and is rejected."""
    with pytest.raises(ValueError, match="code"):
        _finding(code="c" * (MAX_CODE_CHARS + 1))


def test_finding_rejects_an_overlong_summary() -> None:
    """A finding summary past the bound would overflow its column."""
    with pytest.raises(ValueError, match="summary"):
        _finding(summary="s" * (MAX_SUMMARY_CHARS + 1))


def test_finding_rejects_an_overlong_remediation() -> None:
    """A remediation hint past the bound is rejected."""
    with pytest.raises(ValueError, match="remediation"):
        _finding(remediation="r" * (MAX_REMEDIATION_CHARS + 1))


def test_finding_rejects_overlong_subject_text() -> None:
    """The quoted subject text is bounded because a model produces it."""
    with pytest.raises(ValueError, match="subject_text"):
        _finding(subject_text="t" * (MAX_SUBJECT_TEXT_CHARS + 1))


def test_finding_rejects_too_many_citations() -> None:
    """The citation count is bounded to keep one finding's payload small."""
    with pytest.raises(ValueError, match="citations"):
        _finding(citations=tuple(f"src-{index}" for index in range(MAX_CITATIONS + 1)))


def test_finding_rejects_an_overlong_citation() -> None:
    """One citation longer than the bound is rejected."""
    with pytest.raises(ValueError, match="citations"):
        _finding(citations=("c" * (MAX_CITATION_CHARS + 1),))


def test_finding_rejects_a_negative_ordinal() -> None:
    """Ordinals index findings within an evaluation and cannot be negative."""
    with pytest.raises(ValueError, match="ordinal"):
        _finding(ordinal=-1)


# --- evaluation invariants --------------------------------------------------


def test_evaluation_rejects_a_finding_count_that_disagrees() -> None:
    """The summary's count must match the findings actually loaded."""
    with pytest.raises(ValueError, match="finding_count"):
        QaEvaluation(summary_record=_summary(finding_count=1), findings=())


def test_evaluation_rejects_out_of_order_ordinals() -> None:
    """Reordered findings would be persisted with a misleading ordinal."""
    findings = (_finding(ordinal=1), _finding(ordinal=0))

    with pytest.raises(ValueError, match="ordinal"):
        QaEvaluation(summary_record=_summary(finding_count=2), findings=findings)


def test_evaluation_rejects_a_skipped_ordinal() -> None:
    """A gap in the ordinals would silently lose a finding's position."""
    findings = (_finding(ordinal=0), _finding(ordinal=2))

    with pytest.raises(ValueError, match="ordinal"):
        QaEvaluation(summary_record=_summary(finding_count=2), findings=findings)


def test_evaluation_rejects_too_many_findings() -> None:
    """One evaluation cannot exceed the documented finding ceiling."""
    findings = tuple(
        _finding(ordinal=index) for index in range(MAX_FINDINGS_PER_EVALUATION + 1)
    )

    with pytest.raises(ValueError, match="findings"):
        QaEvaluation(
            summary_record=_summary(finding_count=len(findings)), findings=findings
        )


def test_evaluation_accepts_a_consistent_finding_count() -> None:
    """A matching count and consecutive ordinals construct cleanly."""
    findings = (
        _finding(ordinal=0, severity=QaFindingSeverity.HIGH),
        _finding(ordinal=1, is_blocking=True),
    )

    evaluation = QaEvaluation(
        summary_record=_summary(finding_count=2),
        findings=findings,
    )

    assert evaluation.findings == findings, "findings were reordered or altered"
    assert evaluation.summary_record.finding_count == len(findings), (
        "the recorded finding count disagrees with the findings"
    )
