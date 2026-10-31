"""Unit tests for the QA artefact recording and query services.

The service layer owns two contracts the REST and CLI surfaces in later
milestones depend on: ``record_qa_evaluation`` composes into a caller's unit of
work without committing it, while ``QaEvaluationRecorder`` owns the unit of work
and stamps ``evaluated_at`` from its injected clock.
"""

import datetime as dt
import typing as typ
import uuid

import pytest

from episodic.canonical.pagination import Pagination
from episodic.canonical.qa_artefact_ports import QaEvaluationListRequest
from episodic.canonical.qa_artefact_service import (
    QaEvaluationOutcome,
    QaEvaluationRecorder,
    QaEvaluationRecordingRequest,
    QaEvaluatorFailure,
    get_qa_evaluation,
    list_qa_evaluations,
    record_qa_evaluation,
)
from episodic.canonical.qa_artefacts import (
    QaComplianceStatus,
    QaEvaluation,
    QaEvaluationSummary,
    QaEvaluator,
)
from tests.fixtures.qa_artefact_recording_builders import (
    EPISODE_ID,
    EVALUATED_AT,
    EVALUATION_ID,
    TEI_CONTENT_HASH,
    chrono_estimate,
    pedante_finding,
    pedante_result,
)

if typ.TYPE_CHECKING:
    from types import TracebackType

    from episodic.canonical.unit_of_work_protocols import CanonicalUnitOfWork


class _FakeQaArtefactRepository:
    """In-memory stand-in for the persistence port."""

    def __init__(self) -> None:
        self.recorded: list[QaEvaluation] = []
        self.stored: dict[uuid.UUID, QaEvaluation] = {}
        self.listed: list[QaEvaluationListRequest] = []
        self.read: list[uuid.UUID] = []

    async def record_evaluation(self, evaluation: QaEvaluation) -> QaEvaluation:
        """Remember and return the recorded evaluation."""
        self.recorded.append(evaluation)
        self.stored[evaluation.summary_record.id] = evaluation
        return evaluation

    async def get_evaluation(self, evaluation_id: uuid.UUID) -> QaEvaluation | None:
        """Return a remembered evaluation and record that it was read."""
        self.read.append(evaluation_id)
        return self.stored.get(evaluation_id)

    async def list_evaluations(
        self,
        request: QaEvaluationListRequest,
    ) -> tuple[list[QaEvaluationSummary], int]:
        """Return every remembered summary and the matching total."""
        self.listed.append(request)
        summaries = [
            evaluation.summary_record
            for evaluation in self.stored.values()
            if evaluation.summary_record.episode_id == request.episode_id
        ]
        return summaries, len(summaries)


class _FakeUnitOfWork:
    """Unit of work that records how the service used it."""

    def __init__(self) -> None:
        self.qa_artefacts = _FakeQaArtefactRepository()
        self.commit_count = 0
        self.enter_count = 0
        self.exit_count = 0

    async def __aenter__(self) -> _FakeUnitOfWork:
        """Enter the fake transaction."""
        self.enter_count += 1
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Record that the fake transaction closed."""
        self.exit_count += 1

    async def commit(self) -> None:
        """Record that the service committed."""
        self.commit_count += 1


class _FailingRepository(_FakeQaArtefactRepository):
    """Repository whose write always fails."""

    async def record_evaluation(self, evaluation: QaEvaluation) -> QaEvaluation:
        """Reject the write."""
        msg = "the store rejected the write"
        raise RuntimeError(msg)


def _fixed_identifiers() -> uuid.UUID:
    """Return the shared evaluation identifier."""
    return EVALUATION_ID


def _request(outcome: QaEvaluationOutcome) -> QaEvaluationRecordingRequest:
    """Build a fully specified recording command around one outcome."""
    return QaEvaluationRecordingRequest(
        episode_id=EPISODE_ID,
        tei_content_hash=TEI_CONTENT_HASH,
        evaluated_at=EVALUATED_AT,
        outcome=outcome,
        uuid_factory=_fixed_identifiers,
    )


def _uow(fake: _FakeUnitOfWork) -> CanonicalUnitOfWork:
    """Present the fake as the unit-of-work protocol."""
    return typ.cast("CanonicalUnitOfWork", fake)


@pytest.mark.asyncio
async def test_record_qa_evaluation_persists_without_committing() -> None:
    """The composable service records into the caller's transaction only."""
    fake = _FakeUnitOfWork()

    recorded = await record_qa_evaluation(
        _uow(fake),
        _request(pedante_result(pedante_finding())),
    )

    assert fake.qa_artefacts.recorded == [recorded], (
        "the service should persist the mapped evaluation through the port"
    )
    assert fake.commit_count == 0, "the composable service must not commit"
    assert recorded.summary_record.evaluator is QaEvaluator.PEDANTE, (
        "the recorded artefact should name the evaluator that produced it"
    )


@pytest.mark.parametrize(
    ("outcome", "evaluator", "status"),
    [
        (
            pedante_result(pedante_finding()),
            QaEvaluator.PEDANTE,
            QaComplianceStatus.COMPLIANT,
        ),
        (
            chrono_estimate(),
            QaEvaluator.CHRONO,
            QaComplianceStatus.NOT_APPLICABLE,
        ),
        (
            QaEvaluatorFailure(
                evaluator=QaEvaluator.ANTHEM,
                evaluator_version="4",
                error_category="provider_timeout",
                summary="Anthem did not answer.",
            ),
            QaEvaluator.ANTHEM,
            QaComplianceStatus.ERRORED,
        ),
    ],
    ids=["pedante", "chrono", "failure"],
)
@pytest.mark.asyncio
async def test_record_qa_evaluation_dispatches_each_outcome(
    outcome: QaEvaluationOutcome,
    evaluator: QaEvaluator,
    status: QaComplianceStatus,
) -> None:
    """Each supported evaluator outcome maps to its own artefact shape."""
    recorded = await record_qa_evaluation(_uow(_FakeUnitOfWork()), _request(outcome))

    assert recorded.summary_record.evaluator is evaluator, (
        "the wrong evaluator was recorded"
    )
    assert recorded.summary_record.compliance_status is status, (
        "the wrong compliance status was recorded"
    )


@pytest.mark.asyncio
async def test_get_qa_evaluation_returns_the_stored_artefact() -> None:
    """The query service reads one artefact through the port."""
    fake = _FakeUnitOfWork()
    stored = await record_qa_evaluation(
        _uow(fake),
        _request(pedante_result(pedante_finding())),
    )

    found = await get_qa_evaluation(_uow(fake), EVALUATION_ID)

    assert fake.qa_artefacts.read == [EVALUATION_ID], (
        "the query service should ask the port for the requested identifier"
    )
    assert found == stored, "the query service did not return the stored artefact"


@pytest.mark.asyncio
async def test_get_qa_evaluation_returns_none_when_absent() -> None:
    """An unknown identifier is absent, not an error."""
    assert await get_qa_evaluation(_uow(_FakeUnitOfWork()), uuid.uuid7()) is None, (
        "an unknown evaluation identifier should read as absent"
    )


@pytest.mark.asyncio
async def test_list_qa_evaluations_forwards_the_request() -> None:
    """The listing service passes filters and paging through unchanged."""
    fake = _FakeUnitOfWork()
    await record_qa_evaluation(
        _uow(fake),
        _request(pedante_result(pedante_finding())),
    )
    request = QaEvaluationListRequest(
        episode_id=EPISODE_ID,
        pagination=Pagination(limit=10, offset=0),
        evaluator=QaEvaluator.PEDANTE,
    )

    summaries, total = await list_qa_evaluations(_uow(fake), request)

    assert fake.qa_artefacts.listed == [request], (
        "the listing service should forward the request verbatim"
    )
    assert [summary.evaluator for summary in summaries] == [QaEvaluator.PEDANTE], (
        "the listing service should return the stored summaries"
    )
    assert total == 1, "the listing service should return the matching total"


@pytest.mark.asyncio
async def test_recorder_opens_records_and_commits_once() -> None:
    """The application service owns the unit of work it records into."""
    fake = _FakeUnitOfWork()
    recorder = QaEvaluationRecorder(
        uow_factory=lambda: _uow(fake),
        clock=lambda: EVALUATED_AT,
        uuid_factory=_fixed_identifiers,
    )

    recorded = await recorder.record(
        episode_id=EPISODE_ID,
        tei_content_hash=TEI_CONTENT_HASH,
        outcome=pedante_result(pedante_finding()),
    )

    assert fake.enter_count == 1, "the recorder should open exactly one unit of work"
    assert fake.exit_count == 1, "the recorder should close the unit of work"
    assert fake.commit_count == 1, "the recorder should commit exactly once"
    assert fake.qa_artefacts.recorded == [recorded], (
        "the recorder should persist the mapped evaluation"
    )
    assert recorded.summary_record.evaluated_at == EVALUATED_AT, (
        "the recorder should stamp the evaluation time from its clock"
    )


@pytest.mark.asyncio
async def test_recorder_stamps_the_clock_rather_than_the_caller() -> None:
    """Only the recorder's clock decides ``evaluated_at``."""
    fake = _FakeUnitOfWork()
    later = EVALUATED_AT + dt.timedelta(hours=1)
    recorder = QaEvaluationRecorder(
        uow_factory=lambda: _uow(fake),
        clock=lambda: later,
        uuid_factory=_fixed_identifiers,
    )

    recorded = await recorder.record(
        episode_id=EPISODE_ID,
        tei_content_hash=TEI_CONTENT_HASH,
        outcome=pedante_result(pedante_finding()),
    )

    assert recorded.summary_record.evaluated_at == later, (
        "the recorder ignored its injected clock"
    )


@pytest.mark.asyncio
async def test_recorder_replays_the_same_outcome_across_clock_readings() -> None:
    """A repeated recording keeps its key, so the store can replay it."""
    fake = _FakeUnitOfWork()
    outcome = pedante_result(pedante_finding())
    first = QaEvaluationRecorder(
        uow_factory=lambda: _uow(fake),
        clock=lambda: EVALUATED_AT,
        uuid_factory=_fixed_identifiers,
    )
    second = QaEvaluationRecorder(
        uow_factory=lambda: _uow(fake),
        clock=lambda: EVALUATED_AT + dt.timedelta(hours=5),
        uuid_factory=_fixed_identifiers,
    )

    earlier = await first.record(
        episode_id=EPISODE_ID,
        tei_content_hash=TEI_CONTENT_HASH,
        outcome=outcome,
    )
    later = await second.record(
        episode_id=EPISODE_ID,
        tei_content_hash=TEI_CONTENT_HASH,
        outcome=outcome,
    )

    assert (
        earlier.summary_record.idempotency_key == later.summary_record.idempotency_key
    ), "a later recording of the same outcome must replay, not duplicate"


@pytest.mark.asyncio
async def test_recorder_does_not_commit_a_failed_recording() -> None:
    """A rejected write leaves the transaction uncommitted and propagates."""
    fake = _FakeUnitOfWork()
    fake.qa_artefacts = _FailingRepository()
    recorder = QaEvaluationRecorder(
        uow_factory=lambda: _uow(fake),
        clock=lambda: EVALUATED_AT,
        uuid_factory=_fixed_identifiers,
    )

    with pytest.raises(RuntimeError, match="rejected the write"):
        await recorder.record(
            episode_id=EPISODE_ID,
            tei_content_hash=TEI_CONTENT_HASH,
            outcome=pedante_result(pedante_finding()),
        )

    assert fake.commit_count == 0, "a failed recording must not commit"
    assert fake.exit_count == 1, (
        "a failed recording should still close the unit of work"
    )
