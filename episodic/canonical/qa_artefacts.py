"""Domain model for durable quality-assurance (QA) artefacts.

An evaluation is one evaluator run recorded against one canonical episode. It
carries the evaluator's verdict, the policy versions that produced it, and the
findings that justify it, so a later reader can replay why an episode advanced
or was held back without re-running the evaluator.

Two types, not one with a sometimes-empty findings tuple: an empty tuple on a
single type would mean both "this evaluator produced none" and "the list query
did not load them", and no call site could tell those apart. Listing returns
``QaEvaluationSummary``; fetching and recording return ``QaEvaluation``.

``artefact_schema_version`` versions the shape of the payload fields, not the
table columns, which Alembic versions. Adding an optional key does not bump it;
changing the meaning of a key, removing one, or changing the ``code``
vocabulary does.
"""

import dataclasses as dc
import enum
import typing as typ

from .domain_validation import (
    _copy_json_mapping,
    _require_positive_integer,
    _validate_non_empty_text,
)
from .qa_artefact_validation import (
    _normalize_rubric_score,
    _validate_aware_datetime,
    _validate_bounded_text,
    _validate_enum_member,
    _validate_non_negative_integer,
    _validate_optional_non_negative_integer,
)

if typ.TYPE_CHECKING:
    import datetime as dt
    import decimal
    import uuid

    from .domain_enums import JsonMapping

QA_ARTEFACT_SCHEMA_VERSION: int = 1
QA_COMPLIANCE_POLICY_VERSION: int = 1

MAX_FINDINGS_PER_EVALUATION: int = 200
MAX_SUMMARY_CHARS: int = 4096
MAX_REMEDIATION_CHARS: int = 4096
MAX_SUBJECT_TEXT_CHARS: int = 2048
MAX_CODE_CHARS: int = 128
# Identifiers handed back by an evaluator, not prose, so the bound is tight.
MAX_SUBJECT_ID_CHARS: int = 256
MAX_CITATIONS: int = 100
MAX_CITATION_CHARS: int = 256


class QaEvaluator(enum.StrEnum):
    """Evaluator that produced a QA artefact."""

    PEDANTE = "pedante"
    BROMIDE = "bromide"
    CHILTERN = "chiltern"
    ANTHEM = "anthem"
    CAESURA = "caesura"
    CHRONO = "chrono"


class QaComplianceStatus(enum.StrEnum):
    """Whether an evaluation permits the episode to advance."""

    COMPLIANT = "compliant"
    NON_COMPLIANT = "non_compliant"
    NOT_APPLICABLE = "not_applicable"
    ERRORED = "errored"


class QaFindingSeverity(enum.StrEnum):
    """Severity of one QA finding, mirroring the evaluator taxonomy."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


def _validate_citation_sequence(citations: tuple[str, ...]) -> None:
    """Require a tuple holding at most MAX_CITATIONS entries."""
    if not isinstance(citations, tuple):
        msg = "citations must be a tuple of strings."
        raise TypeError(msg)
    if len(citations) > MAX_CITATIONS:
        msg = f"citations must contain at most {MAX_CITATIONS} entries."
        raise ValueError(msg)


def _validate_citation(citation: str) -> None:
    """Require one citation string within MAX_CITATION_CHARS."""
    if not isinstance(citation, str):
        msg = "citations must contain only strings."
        raise TypeError(msg)
    if len(citation) > MAX_CITATION_CHARS:
        msg = f"citations entries must be at most {MAX_CITATION_CHARS} characters."
        raise ValueError(msg)


def _validate_citations(citations: tuple[str, ...]) -> None:
    """Require a bounded tuple of bounded citation strings."""
    _validate_citation_sequence(citations)
    for citation in citations:
        _validate_citation(citation)


@dc.dataclass(frozen=True, slots=True)
class QaFinding:
    """One structured problem reported by an evaluator.

    Attributes
    ----------
    id : uuid.UUID
        Identifier of the finding, distinct from every other finding in the
        same evaluation.
    evaluation_id : uuid.UUID
        Identifier of the owning evaluation; must equal the surrounding
        ``QaEvaluationSummary.id`` when the two are combined.
    ordinal : int
        Zero-based position within the evaluation. Ordinals are consecutive.
    severity : QaFindingSeverity
        Severity drawn from the shared evaluator taxonomy.
    code : str
        Stable machine-readable finding code, bounded by
        :data:`MAX_CODE_CHARS`.
    summary : str
        Human-readable description, bounded by :data:`MAX_SUMMARY_CHARS`.
    remediation : str
        Optional suggested remedy, bounded by :data:`MAX_REMEDIATION_CHARS`.
    subject_id : str
        Identifier of the claim, sentence, or segment under assessment,
        bounded by :data:`MAX_SUBJECT_ID_CHARS`.
    subject_text : str
        Quoted subject text, bounded by :data:`MAX_SUBJECT_TEXT_CHARS`.
    is_blocking : bool
        Whether the finding blocks the episode from advancing. It is set by
        the evaluator's compliance policy and is not derived from
        ``severity``.
    citations : tuple[str, ...]
        Source identifiers supporting the finding: at most
        :data:`MAX_CITATIONS` entries of at most :data:`MAX_CITATION_CHARS`
        characters each.
    details : JsonMapping
        Evaluator-specific JSON payload, deep-copied on construction.
    """

    id: uuid.UUID
    evaluation_id: uuid.UUID
    ordinal: int
    severity: QaFindingSeverity
    code: str
    summary: str
    remediation: str = ""
    subject_id: str = ""
    subject_text: str = ""
    is_blocking: bool = False
    citations: tuple[str, ...] = ()
    details: JsonMapping = dc.field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate field types and the documented bounds."""
        _validate_non_negative_integer(self.ordinal, "ordinal")
        _validate_enum_member(self.severity, "severity", QaFindingSeverity)
        _validate_non_empty_text(self.code, "code")
        _validate_bounded_text(self.code, "code", MAX_CODE_CHARS)
        _validate_bounded_text(self.summary, "summary", MAX_SUMMARY_CHARS)
        _validate_bounded_text(
            self.remediation,
            "remediation",
            MAX_REMEDIATION_CHARS,
        )
        _validate_bounded_text(
            self.subject_id,
            "subject_id",
            MAX_SUBJECT_ID_CHARS,
        )
        _validate_bounded_text(
            self.subject_text,
            "subject_text",
            MAX_SUBJECT_TEXT_CHARS,
        )
        _validate_citations(self.citations)
        _copy_json_mapping(self, "details")


@dc.dataclass(frozen=True, slots=True)
class QaEvaluationSummary:
    """One recorded evaluator invocation, without its findings.

    Attributes
    ----------
    id : uuid.UUID
        Identifier of the evaluation, shared by every finding it owns.
    episode_id : uuid.UUID
        Canonical episode the evaluation applies to.
    evaluator : QaEvaluator
        Evaluator that produced the artefact.
    evaluator_version : str
        Non-empty version of the evaluator's contract.
    artefact_schema_version : int
        Payload schema version that gives ``details`` and
        ``evaluator_metadata`` their meaning. It versions the payload shape,
        not the table columns, which Alembic versions.
    compliance_policy_version : int
        Version of the policy that mapped findings to ``compliance_status``.
    compliance_status : QaComplianceStatus
        Verdict deciding whether the episode may advance.
    evaluated_at : dt.datetime
        Timezone-aware instant at which the evaluator ran.
    idempotency_key : str
        Non-empty key, unique per ``(episode_id, idempotency_key)``, that makes
        a repeated recording return the stored artefact.
    finding_count : int
        Number of findings the evaluation carries; must equal
        ``len(QaEvaluation.findings)`` when the two are combined.
    generation_run_id : uuid.UUID | None
        Launcher run that triggered the evaluation, when one exists.
    summary : str
        Optional human-readable verdict, bounded by
        :data:`MAX_SUMMARY_CHARS`.
    rubric_score : decimal.Decimal | None
        Optional score in ``[0, 1]``, rounded half-to-even to the domain's
        four decimal places on construction, so the value a stored artefact
        reconstructs equals the value this object holds.
    runtime_estimate_seconds : int | None
        Optional non-negative runtime estimate reported by the evaluator.
    evaluator_metadata : JsonMapping
        Evaluator-specific JSON payload, deep-copied on construction.
    created_at : dt.datetime | None
        Timezone-aware storage time, absent until the artefact is recorded.
    """

    id: uuid.UUID
    episode_id: uuid.UUID
    evaluator: QaEvaluator
    evaluator_version: str
    artefact_schema_version: int
    compliance_policy_version: int
    compliance_status: QaComplianceStatus
    evaluated_at: dt.datetime
    idempotency_key: str
    finding_count: int
    generation_run_id: uuid.UUID | None = None
    summary: str = ""
    rubric_score: decimal.Decimal | None = None
    runtime_estimate_seconds: int | None = None
    evaluator_metadata: JsonMapping = dc.field(default_factory=dict)
    created_at: dt.datetime | None = None

    def __post_init__(self) -> None:
        """Validate field types, versions, and the documented bounds."""
        _validate_enum_member(self.evaluator, "evaluator", QaEvaluator)
        _validate_non_empty_text(self.evaluator_version, "evaluator_version")
        _require_positive_integer(
            self.artefact_schema_version,
            "artefact_schema_version",
        )
        _require_positive_integer(
            self.compliance_policy_version,
            "compliance_policy_version",
        )
        _validate_enum_member(
            self.compliance_status,
            "compliance_status",
            QaComplianceStatus,
        )
        _validate_aware_datetime(self.evaluated_at, "evaluated_at")
        _validate_non_empty_text(self.idempotency_key, "idempotency_key")
        _validate_non_negative_integer(self.finding_count, "finding_count")
        _validate_bounded_text(self.summary, "summary", MAX_SUMMARY_CHARS)
        object.__setattr__(
            self,
            "rubric_score",
            _normalize_rubric_score(self.rubric_score),
        )
        _validate_optional_non_negative_integer(
            self.runtime_estimate_seconds,
            "runtime_estimate_seconds",
        )
        if self.created_at is not None:
            _validate_aware_datetime(self.created_at, "created_at")
        _copy_json_mapping(self, "evaluator_metadata")


def _validate_findings_shape(findings: tuple[QaFinding, ...]) -> None:
    """Require an immutable, bounded findings sequence."""
    # A mutable sequence would let the caller change a frozen evaluation
    # after these checks had passed, so only a tuple is accepted.
    if not isinstance(findings, tuple):
        msg = "findings must be a tuple of QaFinding values."
        raise TypeError(msg)
    if len(findings) > MAX_FINDINGS_PER_EVALUATION:
        msg = f"findings must contain at most {MAX_FINDINGS_PER_EVALUATION} entries."
        raise ValueError(msg)


def _validate_finding_count(
    findings: tuple[QaFinding, ...],
    summary_record: QaEvaluationSummary,
) -> None:
    """Require the declared finding count to match the findings."""
    if summary_record.finding_count != len(findings):
        msg = "summary_record.finding_count must equal the number of findings."
        raise ValueError(msg)


def _validate_finding_ownership(
    finding: QaFinding,
    summary_record: QaEvaluationSummary,
) -> None:
    """Require the finding to belong to *summary_record*."""
    if finding.evaluation_id != summary_record.id:
        msg = "every finding's evaluation_id must equal summary_record.id."
        raise ValueError(msg)


def _validate_finding_distinctness(
    finding: QaFinding,
    seen_ids: set[uuid.UUID],
) -> None:
    """Require an unseen id, then record it."""
    if finding.id in seen_ids:
        msg = "findings must carry distinct ids."
        raise ValueError(msg)
    seen_ids.add(finding.id)


def _validate_finding_ordinal(finding: QaFinding, expected_ordinal: int) -> None:
    """Require the finding's ordinal to match its position."""
    if finding.ordinal != expected_ordinal:
        msg = "findings must carry consecutive ordinals starting at zero."
        raise ValueError(msg)


def _validate_findings_against_summary(
    findings: tuple[QaFinding, ...],
    summary_record: QaEvaluationSummary,
) -> None:
    """Require findings that belong to, and are ordered for, their summary."""
    _validate_finding_count(findings, summary_record)
    seen_ids: set[uuid.UUID] = set()
    for expected_ordinal, finding in enumerate(findings):
        if not isinstance(finding, QaFinding):
            msg = "findings must be a tuple of QaFinding values."
            raise TypeError(msg)
        _validate_finding_ownership(finding, summary_record)
        _validate_finding_distinctness(finding, seen_ids)
        _validate_finding_ordinal(finding, expected_ordinal)


@dc.dataclass(frozen=True, slots=True)
class QaEvaluation:
    """One recorded evaluator invocation together with its findings.

    Attributes
    ----------
    summary_record : QaEvaluationSummary
        Header of the evaluation, holding the identity, versions, verdict, and
        recorded finding count.
    findings : tuple[QaFinding, ...]
        Findings in ordinal order. Every finding must carry
        ``summary_record.id`` as its ``evaluation_id`` and an ``id`` distinct
        from its siblings, and the tuple length must equal
        ``summary_record.finding_count``.
    """

    summary_record: QaEvaluationSummary
    findings: tuple[QaFinding, ...] = ()

    def __post_init__(self) -> None:
        """Validate that findings are bounded, owned, distinct, and ordered."""
        _validate_findings_shape(self.findings)
        _validate_findings_against_summary(self.findings, self.summary_record)
