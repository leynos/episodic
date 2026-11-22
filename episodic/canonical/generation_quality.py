"""Generation quality policy and QA outcome values.

The quality mode is the QA policy a client requests for a run. The QA status
is the recorded outcome. :func:`quality_metadata_violation` is the single pure
statement of which ``(quality_mode, status, qa_status, skip_qa_rationale)``
combinations are meaningful, so the run model and its adapters cannot drift
apart.

Policy (decision D5 of ExecPlan 4.4.1)
--------------------------------------
- ``draft_without_qa``: ``qa_status`` is always ``skipped`` and a non-blank
  ``skip_qa_rationale`` is required.
- ``qa_gated``: ``skip_qa_rationale`` must be absent, ``qa_status`` must be
  one of ``pending``, ``passed`` or ``failed``, and ``passed`` holds if and
  only if the run has succeeded.
"""

import enum
import typing as typ

from .domain_enums import GenerationRunStatus


class QualityMode(enum.StrEnum):
    """Requested generation quality policy for a run."""

    DRAFT_WITHOUT_QA = "draft_without_qa"
    QA_GATED = "qa_gated"


class QaStatus(enum.StrEnum):
    """Recorded QA outcome for a run and the TEI it produced."""

    SKIPPED = "skipped"
    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"


_GATED_QA_STATUSES: frozenset[QaStatus] = frozenset({
    QaStatus.PENDING,
    QaStatus.PASSED,
    QaStatus.FAILED,
})


def is_blank_text(value: str | None) -> bool:
    """Return whether a text field is absent or whitespace-only.

    Returns
    -------
    bool
        ``True`` for ``None`` or a whitespace-only string.

    Examples
    --------
    >>> is_blank_text("  "), is_blank_text("Vertical slice."), is_blank_text(None)
    (True, False, True)
    """
    return value is None or not value.strip()


def _no_qa_violation(qa_status: QaStatus | None, rationale: str | None) -> str | None:
    """Return the first no-QA policy violation, if any."""
    if qa_status is not QaStatus.SKIPPED:
        return "qa_status must be skipped for draft_without_qa runs."
    if is_blank_text(rationale):
        return "skip_qa_rationale must be a non-empty string."
    return None


def _gated_violation(
    status: GenerationRunStatus,
    qa_status: QaStatus | None,
    rationale: str | None,
) -> str | None:
    """Return the first QA-gated policy violation, if any."""
    if rationale is not None:
        return "skip_qa_rationale must be absent for qa_gated runs."
    if qa_status not in _GATED_QA_STATUSES:
        return "qa_status must be pending, passed, or failed for qa_gated runs."
    if (qa_status is QaStatus.PASSED) != (status is GenerationRunStatus.SUCCEEDED):
        return "qa_status may be passed for qa_gated runs only when they succeeded."
    return None


def quality_metadata_violation(
    *,
    quality_mode: QualityMode,
    status: GenerationRunStatus,
    qa_status: QaStatus | None,
    skip_qa_rationale: str | None,
) -> str | None:
    """Return the policy violation for a run's quality metadata, if any.

    Parameters
    ----------
    quality_mode : QualityMode
        Requested QA policy.
    status : GenerationRunStatus
        Lifecycle status the metadata is being validated against.
    qa_status : QaStatus | None
        Recorded QA outcome, or ``None`` when it has not been decided.
    skip_qa_rationale : str | None
        Recorded reason for bypassing QA, required only for no-QA runs.

    Returns
    -------
    str | None
        A stable rejection message, or ``None`` when the combination is
        meaningful.

    Examples
    --------
    >>> quality_metadata_violation(
    ...     quality_mode=QualityMode.DRAFT_WITHOUT_QA,
    ...     status=GenerationRunStatus.PENDING,
    ...     qa_status=QaStatus.SKIPPED,
    ...     skip_qa_rationale="Vertical slice.",
    ... ) is None
    True
    """
    match quality_mode:
        case QualityMode.DRAFT_WITHOUT_QA:
            return _no_qa_violation(qa_status, skip_qa_rationale)
        case QualityMode.QA_GATED:
            return _gated_violation(status, qa_status, skip_qa_rationale)
        case _:
            typ.assert_never(quality_mode)
