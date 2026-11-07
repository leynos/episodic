"""Unit tests for the QA artefact persistence port's request value."""

import dataclasses as dc
import uuid

import pytest

from episodic.canonical.pagination import Pagination
from episodic.canonical.qa_artefact_ports import QaEvaluationListRequest
from episodic.canonical.qa_artefacts import QaComplianceStatus, QaEvaluator

_EPISODE_ID = uuid.UUID("0192f9d0-0000-7000-8000-00000000e901")
_PAGINATION = Pagination(limit=25, offset=50)


def test_request_defaults_leave_both_filters_unset() -> None:
    """An unfiltered listing carries no evaluator or status selector."""
    request = QaEvaluationListRequest(
        episode_id=_EPISODE_ID,
        pagination=_PAGINATION,
    )

    assert request.evaluator is None, "the evaluator filter should default to unset"
    assert request.compliance_status is None, (
        "the compliance status filter should default to unset"
    )


def test_request_retains_explicit_filters_and_page() -> None:
    """Explicit selectors survive construction unchanged."""
    request = QaEvaluationListRequest(
        episode_id=_EPISODE_ID,
        pagination=_PAGINATION,
        evaluator=QaEvaluator.CHRONO,
        compliance_status=QaComplianceStatus.ERRORED,
    )

    assert request.episode_id == _EPISODE_ID, "the episode scope changed"
    assert request.pagination == _PAGINATION, "the page selectors changed"
    assert request.evaluator is QaEvaluator.CHRONO, "the evaluator filter changed"
    assert request.compliance_status is QaComplianceStatus.ERRORED, (
        "the compliance status filter changed"
    )


def test_request_is_frozen() -> None:
    """A listing request is a value object, so filters cannot be mutated later."""
    request = QaEvaluationListRequest(
        episode_id=_EPISODE_ID,
        pagination=_PAGINATION,
    )

    with pytest.raises(dc.FrozenInstanceError):
        # The assignment is deliberate: it proves the runtime freeze.
        request.evaluator = QaEvaluator.PEDANTE  # ty: ignore[invalid-assignment]
