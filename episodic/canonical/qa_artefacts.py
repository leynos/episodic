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


def _validate_rubric_score(score: decimal.Decimal | None) -> None:
    """Require an absent or unit-interval score after rounding to storage."""
    if score is None:
        return
    if not isinstance(score, decimal.Decimal):
        msg = "rubric_score must be a decimal.Decimal."
        raise TypeError(msg)
    rounded = score.quantize(_RUBRIC_QUANTUM, rounding=decimal.ROUND_HALF_EVEN)
    if rounded < 0 or rounded > 1:
        msg = (
            "rubric_score must lie within [0, 1] after rounding to four decimal places."
        )
        raise ValueError(msg)


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
    """One structured problem reported by an evaluator."""

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
        _validate_bounded_text(self.code, "code", MAX_CODE_CHARS)
        _validate_bounded_text(self.summary, "summary", MAX_SUMMARY_CHARS)
        _validate_bounded_text(
            self.remediation,
            "remediation",
            MAX_REMEDIATION_CHARS,
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
    """One recorded evaluator invocation, without its findings."""

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
        _validate_enum_member(
            self.compliance_status,
            "compliance_status",
            QaComplianceStatus,
        )
        _validate_aware_datetime(self.evaluated_at, "evaluated_at")
        _validate_non_empty_text(self.idempotency_key, "idempotency_key")
        _validate_non_negative_integer(self.finding_count, "finding_count")
        _validate_bounded_text(self.summary, "summary", MAX_SUMMARY_CHARS)
        _validate_rubric_score(self.rubric_score)
        _validate_optional_non_negative_integer(
            self.runtime_estimate_seconds,
            "runtime_estimate_seconds",
        )
        if self.created_at is not None:
            _validate_aware_datetime(self.created_at, "created_at")
        _copy_json_mapping(self, "evaluator_metadata")


@dc.dataclass(frozen=True, slots=True)
class QaEvaluation:
    """One recorded evaluator invocation together with its findings."""

    summary_record: QaEvaluationSummary
    findings: tuple[QaFinding, ...] = ()

    def __post_init__(self) -> None:
        """Validate that findings are bounded, counted, and ordered."""
        if len(self.findings) > MAX_FINDINGS_PER_EVALUATION:
            msg = (
                f"findings must contain at most {MAX_FINDINGS_PER_EVALUATION} entries."
            )
            raise ValueError(msg)
        if self.summary_record.finding_count != len(self.findings):
            msg = "summary_record.finding_count must equal the number of findings."
            raise ValueError(msg)
        for expected_ordinal, finding in enumerate(self.findings):
            if finding.ordinal != expected_ordinal:
                msg = "findings must carry consecutive ordinals starting at zero."
                raise ValueError(msg)
