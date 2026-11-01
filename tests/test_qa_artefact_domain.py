"""Unit tests for the QA artefact domain model and its compliance policy.

Discharges the obligations the ExecPlan assigns to this module: ``INV-BLOCKING-
SET``, ``INV-ENUM-TAXONOMY``, the domain half of ``INV-TIMEZONE``, and every
``__post_init__`` rejection that is not the rubric-score storage contract. The
blocking set is authored in ``tests/fixtures/qa_artefact_builders.py`` rather
than read from the production module, because ``INV-COMPLIANCE-BLOCKING``
inherits the set from the code under test and cannot detect a wrong one on its
own. Rubric-score precision is covered by
``tests/test_qa_artefact_rubric_score.py``.
"""

import datetime as dt
import typing as typ
import uuid

import pytest

from episodic.canonical.qa_artefacts import (
    MAX_CITATION_CHARS,
    MAX_CITATIONS,
    MAX_CODE_CHARS,
    MAX_FINDINGS_PER_EVALUATION,
    MAX_REMEDIATION_CHARS,
    MAX_SUBJECT_ID_CHARS,
    MAX_SUBJECT_TEXT_CHARS,
    MAX_SUMMARY_CHARS,
    QaComplianceStatus,
    QaEvaluation,
    QaEvaluationSummary,
    QaEvaluator,
    QaFinding,
    QaFindingSeverity,
)
from episodic.qa.pedante import ClaimKind, FindingSeverity, PedanteFinding, SupportLevel
from episodic.qa.pedante.types import _BLOCKING_SUPPORT_LEVELS
from tests.fixtures.qa_artefact_builders import (
    DOCUMENTED_BLOCKING_LEVELS,
    EVALUATED_AT,
    FINDING_ID,
    OTHER_EVALUATION_ID,
    OTHER_FINDING_ID,
    finding,
    summary,
)

if typ.TYPE_CHECKING:
    import collections.abc as cabc

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


# --- INV-BLOCKING-SET -------------------------------------------------------


@pytest.mark.parametrize("support_level", list(SupportLevel))
def test_blocking_flag_follows_the_documented_policy(
    support_level: SupportLevel,
) -> None:
    """Every taxonomy member blocks exactly when the policy says it does."""
    assert _pedante_finding(support_level).is_blocking is (
        support_level in DOCUMENTED_BLOCKING_LEVELS
    ), f"{support_level.value} disagrees with the documented blocking policy"


def test_documented_blocking_set_matches_the_production_set() -> None:
    """The independently authored set has not drifted from production."""
    assert DOCUMENTED_BLOCKING_LEVELS == _BLOCKING_SUPPORT_LEVELS, (
        "the test's independent blocking set and the production set have drifted"
    )
    assert len(DOCUMENTED_BLOCKING_LEVELS) == 8, (
        "the documented blocking set changed size; re-check the policy"
    )


def test_documented_blocking_set_is_a_strict_subset_of_the_taxonomy() -> None:
    """A set equal to the taxonomy would make every finding blocking."""
    assert set(SupportLevel) > DOCUMENTED_BLOCKING_LEVELS, (
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
        summary(evaluated_at=EVALUATED_AT.replace(tzinfo=None))


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

    stored = summary(evaluated_at=moment).evaluated_at

    assert stored == moment, "the stored instant differs from the supplied one"
    assert stored.tzinfo is not None, "the stored timestamp lost its zone"
    assert stored.utcoffset() == tz.utcoffset(None), "the stored offset changed"


# --- summary rejections -----------------------------------------------------


@pytest.mark.parametrize(
    ("field_name", "build"),
    [
        ("runtime_estimate_seconds", lambda: summary(runtime_estimate_seconds=-1)),
        ("evaluator_version", lambda: summary(evaluator_version="")),
        ("evaluator_version", lambda: summary(evaluator_version="   ")),
        ("idempotency_key", lambda: summary(idempotency_key="")),
        ("summary", lambda: summary(summary="x" * (MAX_SUMMARY_CHARS + 1))),
        # A version number identifies a contract, so zero, a negative, and a
        # boolean (an int subclass that means neither) are all unusable.
        ("artefact_schema_version", lambda: summary(artefact_schema_version=0)),
        ("artefact_schema_version", lambda: summary(artefact_schema_version=-1)),
        ("artefact_schema_version", lambda: summary(artefact_schema_version=True)),
        ("compliance_policy_version", lambda: summary(compliance_policy_version=0)),
        ("compliance_policy_version", lambda: summary(compliance_policy_version=-1)),
        ("compliance_policy_version", lambda: summary(compliance_policy_version=True)),
    ],
)
def test_summary_rejects_invalid_field_values(
    field_name: str,
    build: cabc.Callable[[], QaEvaluationSummary],
) -> None:
    """Each documented bound rejects a value just past it."""
    with pytest.raises((TypeError, ValueError), match=field_name):
        build()


# --- defensive copying ------------------------------------------------------


def test_finding_copies_nested_details() -> None:
    """A nested evaluator payload cannot be changed through the caller's dict."""
    evidence = {"source": "A"}
    recorded = finding(details={"evidence": evidence})

    evidence["source"] = "B"

    assert recorded.details == {"evidence": {"source": "A"}}, (
        "the nested details payload was retained by reference"
    )


def test_summary_copies_nested_evaluator_metadata() -> None:
    """A nested metadata payload cannot be changed through the caller's dict."""
    metadata = {"model": "pedante"}
    recorded = summary(evaluator_metadata={"run": metadata})

    metadata["model"] = "changed"

    assert recorded.evaluator_metadata == {"run": {"model": "pedante"}}, (
        "the nested evaluator metadata was retained by reference"
    )


# --- finding rejections -----------------------------------------------------


@pytest.mark.parametrize(
    ("field_name", "build"),
    [
        # A blank code is unusable because consumers filter on it.
        ("code", lambda: finding(code="")),
        ("code", lambda: finding(code="   ")),
        # Everything below is a value just past its documented bound.
        ("code", lambda: finding(code="c" * (MAX_CODE_CHARS + 1))),
        ("subject_id", lambda: finding(subject_id="s" * (MAX_SUBJECT_ID_CHARS + 1))),
        ("summary", lambda: finding(summary="s" * (MAX_SUMMARY_CHARS + 1))),
        (
            "remediation",
            lambda: finding(remediation="r" * (MAX_REMEDIATION_CHARS + 1)),
        ),
        (
            "subject_text",
            lambda: finding(subject_text="t" * (MAX_SUBJECT_TEXT_CHARS + 1)),
        ),
        (
            "citations",
            lambda: finding(
                citations=tuple(f"src-{index}" for index in range(MAX_CITATIONS + 1))
            ),
        ),
        ("citations", lambda: finding(citations=("c" * (MAX_CITATION_CHARS + 1),))),
        ("ordinal", lambda: finding(ordinal=-1)),
    ],
)
def test_finding_rejects_invalid_field_values(
    field_name: str,
    build: cabc.Callable[[], QaFinding],
) -> None:
    """Each documented bound rejects a value just past it."""
    with pytest.raises(ValueError, match=field_name):
        build()


# --- evaluation invariants --------------------------------------------------


def test_evaluation_rejects_a_mutable_findings_sequence() -> None:
    """A list would let the caller change a frozen evaluation afterwards."""
    mutable = typ.cast("tuple[QaFinding, ...]", [finding()])

    with pytest.raises(TypeError, match="findings"):
        QaEvaluation(summary_record=summary(finding_count=1), findings=mutable)


def test_evaluation_rejects_entries_that_are_not_findings() -> None:
    """An arbitrary object has none of the attributes later reads rely on."""
    entries = typ.cast("tuple[QaFinding, ...]", (object(),))

    with pytest.raises(TypeError, match="findings"):
        QaEvaluation(summary_record=summary(finding_count=1), findings=entries)


def test_evaluation_rejects_a_finding_count_that_disagrees() -> None:
    """The summary's count must match the findings actually loaded."""
    with pytest.raises(ValueError, match="finding_count"):
        QaEvaluation(summary_record=summary(finding_count=1), findings=())


def test_evaluation_rejects_findings_from_another_evaluation() -> None:
    """A finding's evaluation_id must name the owning summary."""
    findings = (finding(evaluation_id=OTHER_EVALUATION_ID),)

    with pytest.raises(ValueError, match="evaluation_id"):
        QaEvaluation(summary_record=summary(finding_count=1), findings=findings)


def test_evaluation_rejects_duplicate_finding_ids() -> None:
    """Findings are addressed by id, so two findings cannot share one."""
    findings = (finding(ordinal=0), finding(ordinal=1))

    with pytest.raises(ValueError, match="distinct ids"):
        QaEvaluation(summary_record=summary(finding_count=2), findings=findings)


@pytest.mark.parametrize(("first_ordinal", "second_ordinal"), [(1, 0), (0, 2)])
def test_evaluation_rejects_non_consecutive_ordinals(
    first_ordinal: int,
    second_ordinal: int,
) -> None:
    """Reordered or gapped findings would persist a misleading position."""
    findings = (
        finding(finding_id=FINDING_ID, ordinal=first_ordinal),
        finding(finding_id=OTHER_FINDING_ID, ordinal=second_ordinal),
    )

    with pytest.raises(ValueError, match="ordinal"):
        QaEvaluation(summary_record=summary(finding_count=2), findings=findings)


def test_evaluation_rejects_too_many_findings() -> None:
    """One evaluation cannot exceed the documented finding ceiling."""
    # Distinct ids and consecutive ordinals leave the ceiling as the only
    # violated rule, so the rejection cannot be satisfied by another check.
    findings = tuple(
        finding(finding_id=uuid.uuid5(FINDING_ID, str(index)), ordinal=index)
        for index in range(MAX_FINDINGS_PER_EVALUATION + 1)
    )

    with pytest.raises(
        ValueError, match=f"at most {MAX_FINDINGS_PER_EVALUATION} entries"
    ):
        QaEvaluation(
            summary_record=summary(finding_count=len(findings)), findings=findings
        )


def test_evaluation_accepts_a_consistent_finding_count() -> None:
    """A matching count and consecutive ordinals construct cleanly."""
    findings = (
        finding(finding_id=FINDING_ID, ordinal=0, severity=QaFindingSeverity.HIGH),
        finding(finding_id=OTHER_FINDING_ID, ordinal=1, is_blocking=True),
    )

    evaluation = QaEvaluation(
        summary_record=summary(finding_count=2),
        findings=findings,
    )

    assert evaluation.findings == findings, "findings were reordered or altered"
    assert evaluation.summary_record.finding_count == len(findings), (
        "the recorded finding count disagrees with the findings"
    )
