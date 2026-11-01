"""Generative statements of the QA artefact recording invariants.

``INV-COMPLIANCE-BLOCKING`` and ``INV-MAPPING-FIDELITY`` both quantify over
Pedante results, so they are properties rather than cases. Each property emits
a ``hypothesis.event`` for the branch it took, which lets a deliberate policy
or mapper defect be observed as a counter-example instead of a vacuous pass.
"""

import hypothesis
import hypothesis.strategies as st
from hypothesis import given, settings

from episodic.canonical.qa_artefact_compliance import compliance_status_for_pedante
from episodic.canonical.qa_artefact_recording import (
    evaluation_from_pedante,
)
from episodic.canonical.qa_artefacts import (
    QaComplianceStatus,
    QaFindingSeverity,
)
from episodic.qa.pedante.types import (
    ClaimKind,
    FindingSeverity,
    PedanteFinding,
    SupportLevel,
)
from tests.fixtures.qa_artefact_builders import DOCUMENTED_BLOCKING_LEVELS
from tests.fixtures.qa_artefact_recording_builders import (
    EPISODE_ID,
    EVALUATED_AT,
    TEI_CONTENT_HASH,
    pedante_result,
)

_IDENTIFIER = st.from_regex(r"[A-Za-z0-9_-]{1,24}", fullmatch=True)
_BLANK = st.text(min_size=1, max_size=40).filter(lambda value: bool(value.strip()))
_NON_ASCII_PROSE = st.sampled_from([
    "Café — naïve façade.",
    "日本語の主張。",
    "Ελληνικά στη σκηνή.",
])
_PROSE = st.one_of(_BLANK, _NON_ASCII_PROSE)
_CLAIM_KINDS = st.sampled_from(list(ClaimKind))
_SUPPORT_LEVELS = st.sampled_from(list(SupportLevel))
_SEVERITIES = st.sampled_from(list(FindingSeverity))


@st.composite
def _pedante_findings(draw: st.DrawFn) -> PedanteFinding:
    """Draw one valid Pedante finding across the whole evaluator taxonomy."""
    return PedanteFinding(
        claim_id=draw(_IDENTIFIER),
        claim_text=draw(_PROSE),
        claim_kind=draw(_CLAIM_KINDS),
        support_level=draw(_SUPPORT_LEVELS),
        severity=draw(_SEVERITIES),
        summary=draw(_PROSE),
        remediation=draw(_PROSE),
        cited_source_ids=draw(st.lists(_IDENTIFIER, min_size=0, max_size=3).map(tuple)),
    )


@settings(max_examples=100, deadline=None)
@given(findings=st.lists(_pedante_findings(), max_size=8))
def test_compliance_status_tracks_blocking_findings(
    findings: list[PedanteFinding],
) -> None:
    """A mapped evaluation is non-compliant exactly when a finding blocks."""
    evaluation = evaluation_from_pedante(
        pedante_result(*findings),
        episode_id=EPISODE_ID,
        tei_content_hash=TEI_CONTENT_HASH,
        evaluated_at=EVALUATED_AT,
    )
    has_blocking = any(finding.is_blocking for finding in evaluation.findings)
    hypothesis.event("blocking present" if has_blocking else "no blocking finding")

    assert (
        evaluation.summary_record.compliance_status is QaComplianceStatus.NON_COMPLIANT
    ) is has_blocking, "the verdict and the mapped findings disagree"


@settings(max_examples=100, deadline=None)
@given(findings=st.lists(_pedante_findings(), max_size=8))
def test_projection_preserves_every_field(findings: list[PedanteFinding]) -> None:
    """Every field the projection claims to carry arrives unchanged."""
    evaluation = evaluation_from_pedante(
        pedante_result(*findings),
        episode_id=EPISODE_ID,
        tei_content_hash=TEI_CONTENT_HASH,
        evaluated_at=EVALUATED_AT,
    )
    if any(not finding.cited_source_ids for finding in findings):
        hypothesis.event("finding without citations")
    if any(len(finding.cited_source_ids) == 3 for finding in findings):
        hypothesis.event("finding with three citations")
    if any(not finding.claim_text.isascii() for finding in findings):
        hypothesis.event("non-ASCII claim text")

    assert len(evaluation.findings) == len(findings), (
        "the projection changed the number of findings"
    )
    assert evaluation.summary_record.finding_count == len(findings), (
        "the recorded finding count disagrees with the findings"
    )
    for ordinal, (source, derived) in enumerate(
        zip(findings, evaluation.findings, strict=True)
    ):
        assert derived.ordinal == ordinal, "the finding ordinal is not its position"
        assert derived.code == source.support_level.value, (
            "the finding code is not the raw support level"
        )
        assert derived.subject_id == source.claim_id, (
            "the subject identifier is not the claim identifier"
        )
        assert derived.subject_text == source.claim_text, (
            "the subject text is not the verbatim claim text"
        )
        assert derived.citations == source.cited_source_ids, (
            "the cited source identifiers were not carried"
        )
        assert derived.details == {"claim_kind": source.claim_kind.value}, (
            "the claim kind was not preserved in the details payload"
        )
        assert derived.severity is QaFindingSeverity(source.severity.value), (
            "the severity did not map onto the shared taxonomy"
        )
        assert derived.summary == source.summary, "the finding summary was altered"
        assert derived.remediation == source.remediation, (
            "the remediation guidance was altered"
        )
        assert derived.is_blocking == source.is_blocking, (
            "the blocking flag was not carried"
        )


@settings(max_examples=50, deadline=None)
@given(
    support_levels=st.lists(
        st.sampled_from(list(SupportLevel)),
        max_size=8,
    )
)
def test_only_the_documented_blocking_levels_make_a_result_non_compliant(
    support_levels: list[SupportLevel],
) -> None:
    """The policy verdict follows the blocking set ADR 001 describes."""
    findings = [
        PedanteFinding(
            claim_id=f"claim-{index}",
            claim_text="A claim.",
            claim_kind=ClaimKind.DIRECT_QUOTE,
            support_level=support_level,
            severity=FindingSeverity.LOW,
            summary="A finding.",
            remediation="A remedy.",
            cited_source_ids=(),
        )
        for index, support_level in enumerate(support_levels)
    ]
    expected = (
        QaComplianceStatus.NON_COMPLIANT
        if any(level in DOCUMENTED_BLOCKING_LEVELS for level in support_levels)
        else QaComplianceStatus.COMPLIANT
    )

    assert compliance_status_for_pedante(pedante_result(*findings)) is expected, (
        "the verdict disagreed with the documented blocking set"
    )
