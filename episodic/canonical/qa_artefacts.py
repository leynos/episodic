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
import datetime as dt
import decimal
import enum
import typing as typ

from .domain_validation import (
    _copy_json_mapping,
    _validate_non_empty_text,
)

if typ.TYPE_CHECKING:
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

# Rubric scores are stored as NUMERIC(5, 4), so the unit interval is enforced
# on the rounded value that would actually be persisted.
_RUBRIC_QUANTUM = decimal.Decimal("0.0001")


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


def _validate_enum_member(
    value: object,
    field_name: str,
    enum_type: type[enum.StrEnum],
) -> None:
    """Require an exact member of *enum_type*."""
    if not isinstance(value, enum_type):
        msg = f"{field_name} must be a {enum_type.__name__} value."
        raise TypeError(msg)


def _validate_bounded_text(value: str, field_name: str, limit: int) -> None:
    """Require a string no longer than *limit* characters."""
    if not isinstance(value, str):
        msg = f"{field_name} must be a string."
        raise TypeError(msg)
    if len(value) > limit:
        msg = f"{field_name} must be at most {limit} characters."
        raise ValueError(msg)


def _validate_non_negative_integer(value: int, field_name: str) -> None:
    """Require an exact non-negative integer, excluding booleans."""
    if type(value) is not int or value < 0:
        msg = f"{field_name} must be a non-negative integer."
        raise ValueError(msg)


def _validate_positive_integer(value: int, field_name: str) -> None:
    """Require an exact positive integer, excluding booleans."""
    if type(value) is not int or value < 1:
        msg = f"{field_name} must be a positive integer."
        raise ValueError(msg)


def _validate_optional_non_negative_integer(
    value: int | None,
    field_name: str,
) -> None:
    """Require an absent or non-negative integer value."""
    if value is not None:
        _validate_non_negative_integer(value, field_name)


def _validate_aware_datetime(value: dt.datetime, field_name: str) -> None:
    """Require a timezone-aware datetime."""
    if not isinstance(value, dt.datetime):
        msg = f"{field_name} must be a datetime."
        raise TypeError(msg)
    if value.tzinfo is None or value.utcoffset() is None:
        msg = f"{field_name} must be timezone-aware."
        raise ValueError(msg)


def _normalize_rubric_score(
    score: decimal.Decimal | None,
) -> decimal.Decimal | None:
    """Return *score* at the stored precision, rejecting unusable values."""
    if score is None:
        return None
    if not isinstance(score, decimal.Decimal):
        msg = "rubric_score must be a decimal.Decimal."
        raise TypeError(msg)
    if not score.is_finite():
        # PostgreSQL stores NaN in a NUMERIC column verbatim, so it would slip
        # past the interval check below and later fail an ordering comparison.
        msg = "rubric_score must be a finite decimal."
        raise ValueError(msg)
    try:
        rounded = score.quantize(_RUBRIC_QUANTUM, rounding=decimal.ROUND_HALF_EVEN)
    except decimal.InvalidOperation as exc:
        msg = "rubric_score must be representable at four decimal places."
        raise ValueError(msg) from exc
    if rounded < 0 or rounded > 1:
        msg = (
            "rubric_score must lie within [0, 1] after rounding to four decimal places."
        )
        raise ValueError(msg)
    # A rounded negative zero compares equal to zero but serializes as -0.0.
    return rounded.copy_abs() if rounded.is_zero() else rounded


def _validate_citations(citations: tuple[str, ...]) -> None:
    """Require a bounded tuple of bounded citation strings."""
    if not isinstance(citations, tuple):
        msg = "citations must be a tuple of strings."
        raise TypeError(msg)
    if len(citations) > MAX_CITATIONS:
        msg = f"citations must contain at most {MAX_CITATIONS} entries."
        raise ValueError(msg)
    for citation in citations:
        if not isinstance(citation, str):
            msg = "citations must contain only strings."
            raise TypeError(msg)
        if len(citation) > MAX_CITATION_CHARS:
            msg = f"citations entries must be at most {MAX_CITATION_CHARS} characters."
            raise ValueError(msg)


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
        Evaluator-specific JSON payload, copied defensively on construction.
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
        Optional score in ``[0, 1]``, rounded half-to-even to four decimal
        places on construction to match the ``NUMERIC(5, 4)`` column, so the
        value read back equals the value stored.
    runtime_estimate_seconds : int | None
        Optional non-negative runtime estimate reported by the evaluator.
    evaluator_metadata : JsonMapping
        Evaluator-specific JSON payload, copied defensively on construction.
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
        _validate_positive_integer(
            self.artefact_schema_version,
            "artefact_schema_version",
        )
        _validate_positive_integer(
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
        if len(self.findings) > MAX_FINDINGS_PER_EVALUATION:
            msg = (
                f"findings must contain at most {MAX_FINDINGS_PER_EVALUATION} entries."
            )
            raise ValueError(msg)
        if self.summary_record.finding_count != len(self.findings):
            msg = "summary_record.finding_count must equal the number of findings."
            raise ValueError(msg)
        seen_ids: set[uuid.UUID] = set()
        for expected_ordinal, finding in enumerate(self.findings):
            if finding.evaluation_id != self.summary_record.id:
                msg = "every finding's evaluation_id must equal summary_record.id."
                raise ValueError(msg)
            if finding.id in seen_ids:
                msg = "findings must carry distinct ids."
                raise ValueError(msg)
            seen_ids.add(finding.id)
            if finding.ordinal != expected_ordinal:
                msg = "findings must carry consecutive ordinals starting at zero."
                raise ValueError(msg)
