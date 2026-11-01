"""QA artefact replay and supersession contract tests.

Covers ``INV-REPLAY-IDEMPOTENT`` and ``INV-ERRORED-SUPERSEDED``: replaying a
key returns the artefact the first recording created, an errored artefact is
superseded in place, and only the idempotency constraint counts as a replay.
"""

import datetime as dt
import typing as typ
import uuid

import hypothesis.strategies as st
import pytest
import sqlalchemy as sa
from hypothesis import HealthCheck, given, settings
from sqlalchemy.exc import IntegrityError

from episodic.canonical.qa_artefacts import (
    QaComplianceStatus,
    QaFindingSeverity,
)
from episodic.canonical.storage import (
    QaArtefactStorageRuntime,
    QaEvaluationRecord,
    QaFindingRecord,
    SqlAlchemyQaArtefactStore,
    SqlAlchemyUnitOfWork,
)
from episodic.canonical.storage.integrity_helpers import constraint_name
from tests.canonical_storage._qa_artefact_support import (
    EvaluationOptions,
    count_artefacts_for,
    count_rows,
    create_episode,
    make_evaluation,
)
from tests.canonical_storage._workflow_checkpoint_support import RecordingMetrics

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    type SessionFactory = async_sessionmaker[AsyncSession]
else:
    type SessionFactory = object

REPLAYED_AT = dt.datetime(2026, 10, 31, 10, 0, tzinfo=dt.UTC)
_KEYS = ("key-a", "key-b", "key-c")
_STATUSES = (
    QaComplianceStatus.COMPLIANT,
    QaComplianceStatus.NON_COMPLIANT,
    QaComplianceStatus.ERRORED,
)
_OPERATIONS = st.lists(
    st.tuples(
        st.integers(min_value=0, max_value=1),
        st.sampled_from(_KEYS),
        st.sampled_from(_STATUSES),
    ),
    min_size=0,
    max_size=8,
)


@pytest.mark.asyncio
async def test_replay_returns_the_first_recording(
    session_factory: SessionFactory,
) -> None:
    """A repeated key returns the stored artefact, not the new payload."""
    episode_id = await create_episode(session_factory)
    first = make_evaluation(
        episode_id,
        idempotency_key="replay",
        options=EvaluationOptions(severities=(QaFindingSeverity.LOW,)),
    )
    repeat = make_evaluation(
        episode_id,
        idempotency_key="replay",
        options=EvaluationOptions(
            severities=(QaFindingSeverity.HIGH, QaFindingSeverity.HIGH),
            evaluated_at=REPLAYED_AT,
        ),
    )

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        stored_first = await uow.qa_artefacts.record_evaluation(first)
        stored_repeat = await uow.qa_artefacts.record_evaluation(repeat)
        await uow.commit()

    async with session_factory() as session:
        assert await count_rows(session, QaEvaluationRecord) == 1, (
            "a replay should not create a second evaluation row"
        )
        assert await count_rows(session, QaFindingRecord) == 1, (
            "a replay should not create a second set of findings"
        )
    assert stored_repeat == stored_first, (
        "a replay should return the stored artefact unchanged"
    )
    assert stored_repeat.summary_record.id == first.summary_record.id, (
        "a replay should return the identifier created by the first recording"
    )


@pytest.mark.parametrize(
    ("stored_status", "incoming_status", "is_superseded"),
    [
        (QaComplianceStatus.COMPLIANT, QaComplianceStatus.COMPLIANT, False),
        (QaComplianceStatus.COMPLIANT, QaComplianceStatus.ERRORED, False),
        (QaComplianceStatus.NON_COMPLIANT, QaComplianceStatus.COMPLIANT, False),
        (QaComplianceStatus.NON_COMPLIANT, QaComplianceStatus.ERRORED, False),
        (QaComplianceStatus.NOT_APPLICABLE, QaComplianceStatus.COMPLIANT, False),
        (QaComplianceStatus.NOT_APPLICABLE, QaComplianceStatus.ERRORED, False),
        (QaComplianceStatus.ERRORED, QaComplianceStatus.COMPLIANT, True),
        (QaComplianceStatus.ERRORED, QaComplianceStatus.NON_COMPLIANT, True),
        (QaComplianceStatus.ERRORED, QaComplianceStatus.ERRORED, False),
    ],
)
@pytest.mark.asyncio
async def test_errored_artefact_is_superseded_in_place(
    session_factory: SessionFactory,
    stored_status: QaComplianceStatus,
    incoming_status: QaComplianceStatus,
    *,
    is_superseded: bool,
) -> None:
    """Only an errored artefact is replaced, and it keeps its identifier."""
    episode_id = await create_episode(session_factory)
    first = make_evaluation(
        episode_id,
        idempotency_key="supersede",
        options=EvaluationOptions(
            compliance_status=stored_status,
            severities=(QaFindingSeverity.LOW,),
        ),
    )
    incoming = make_evaluation(
        episode_id,
        idempotency_key="supersede",
        options=EvaluationOptions(
            compliance_status=incoming_status,
            severities=(QaFindingSeverity.HIGH, QaFindingSeverity.HIGH),
            evaluated_at=REPLAYED_AT,
        ),
    )

    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        stored_first = await uow.qa_artefacts.record_evaluation(first)
        stored_repeat = await uow.qa_artefacts.record_evaluation(incoming)
        await uow.commit()

    assert stored_repeat.summary_record.id == first.summary_record.id, (
        "supersession should keep the stored identifier"
    )
    async with session_factory() as session:
        assert await count_rows(session, QaEvaluationRecord) == 1, (
            "supersession should not create a second evaluation row"
        )
        assert await count_rows(session, QaFindingRecord) == (
            2 if is_superseded else 1
        ), "only a superseding recording should replace the findings"

    if not is_superseded:
        assert stored_repeat == stored_first, (
            "a non-superseding replay should return the stored artefact unchanged"
        )
        return

    assert stored_repeat.summary_record.compliance_status is incoming_status, (
        "the superseded artefact should carry the incoming verdict"
    )
    assert stored_repeat.summary_record.evaluated_at == REPLAYED_AT, (
        "the superseded artefact should carry the incoming evaluation time"
    )
    assert [item.severity for item in stored_repeat.findings] == [
        QaFindingSeverity.HIGH,
        QaFindingSeverity.HIGH,
    ], "the superseded artefact should carry the incoming findings"


@pytest.mark.asyncio
async def test_non_idempotency_violation_is_not_treated_as_replay(
    session_factory: SessionFactory,
) -> None:
    """A violation of another constraint reaches the caller as an integrity error.

    The rejected row belongs to the store alone, so the savepoint also has to
    leave the caller's transaction usable.
    """
    # The episode does not exist, so the evaluation's foreign key rejects the
    # insert. That keeps the failure inside the store's own savepoint, unlike a
    # caller-owned pending row, whose failed insert invalidates the outer
    # transaction however the savepoint is rolled back.
    orphan = make_evaluation(
        uuid.uuid7(),
        idempotency_key="orphan",
        options=EvaluationOptions(severities=(QaFindingSeverity.LOW,)),
    )
    metrics = RecordingMetrics()
    async with session_factory() as session:
        store = SqlAlchemyQaArtefactStore(
            session,
            runtime=QaArtefactStorageRuntime(
                clock=lambda: REPLAYED_AT,
                uuid_factory=uuid.uuid7,
                metrics=metrics,
            ),
        )
        with pytest.raises(IntegrityError) as exc_info:
            await store.record_evaluation(orphan)
        assert await session.scalar(sa.text("SELECT 1")) == 1, (
            "a non-idempotency violation should leave the transaction usable"
        )
        await session.rollback()

    assert constraint_name(exc_info.value) == "qa_evaluations_episode_id_fkey", (
        "the rejected constraint should be the evaluation's episode foreign key"
    )
    assert metrics.counters == [
        (
            "qa_evaluation_record_failed",
            {"evaluator": "pedante", "error_category": "integrity_violation"},
        )
    ], (
        "the failure should be named for the constraint that fired; without the "
        "narrowing the replay lookup finds no row and reports conflict_without_row"
    )
    async with session_factory() as session:
        assert await count_rows(session, QaEvaluationRecord) == 0, (
            "a rejected first recording should leave no evaluation behind"
        )


@given(operations=_OPERATIONS)
@settings(
    max_examples=6,
    deadline=None,
    suppress_health_check=[
        HealthCheck.function_scoped_fixture,
        HealthCheck.filter_too_much,
    ],
)
@pytest.mark.asyncio
async def test_replaying_keys_never_multiplies_artefacts(
    session_factory: SessionFactory,
    operations: list[tuple[int, str, QaComplianceStatus]],
) -> None:
    """Replayed operation sequences keep one row per episode and key."""
    factory = session_factory
    episode_ids = [await create_episode(factory) for _ in range(2)]
    # The leading pair records the same key twice, so every example replays.
    sequence = [
        (0, "repeat-key", QaComplianceStatus.COMPLIANT),
        (0, "repeat-key", QaComplianceStatus.COMPLIANT),
        *operations,
    ]
    first_ids: dict[tuple[uuid.UUID, str], uuid.UUID] = {}
    replays = 0

    for episode_index, key, status in sequence:
        evaluation = make_evaluation(
            episode_ids[episode_index],
            idempotency_key=key,
            options=EvaluationOptions(
                compliance_status=status,
                severities=(QaFindingSeverity.LOW,),
            ),
        )
        async with SqlAlchemyUnitOfWork(factory) as uow:
            stored = await uow.qa_artefacts.record_evaluation(evaluation)
            await uow.commit()
        identity = (episode_ids[episode_index], key)
        if identity in first_ids:
            replays += 1
            assert stored.summary_record.id == first_ids[identity], (
                "a replay should return the identifier created first"
            )
        else:
            first_ids[identity] = stored.summary_record.id
            assert stored.summary_record.id == evaluation.summary_record.id, (
                "a first recording should keep the caller's identifier"
            )

    assert replays >= 1, "the sequence should contain at least one replay"
    async with factory() as session:
        evaluations, findings = await count_artefacts_for(session, episode_ids)
    assert evaluations == len(first_ids), (
        "each episode and key pair should hold exactly one evaluation row"
    )
    assert findings == len(first_ids), (
        "each stored evaluation should hold exactly one finding row"
    )
