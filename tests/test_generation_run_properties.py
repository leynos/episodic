"""Property tests for generation-run event-log invariants.

These tests exercise `InMemoryGenerationRunStore` with generated event batches
and operation sequences, covering monotonic per-run sequence numbers, gap-free
streams, timestamp ordering, event multiset preservation, run isolation,
idempotency stability, terminal immutability, and cursor paging.
"""

import asyncio
import collections
import collections.abc as cabc
import dataclasses
import datetime as dt
import itertools
import typing as typ
import uuid

import hypothesis.strategies as st
import pytest
from hypothesis import given, settings

from episodic.canonical.adapters.generation_runs import InMemoryGenerationRunStore
from episodic.canonical.domain import GenerationRun, GenerationRunStatus
from episodic.canonical.generation_quality import QaStatus, QualityMode
from episodic.canonical.generation_run_errors import RunAlreadyTerminal
from episodic.canonical.generation_run_ports import event_seq

NOW = dt.datetime(2026, 6, 4, 8, 0, tzinfo=dt.UTC)
type EventInput = tuple[str, dict[str, object]]
type EventInputs = list[EventInput] | tuple[EventInput, ...]
type AdapterOperation = tuple[str, EventInput | GenerationRunStatus | None]

EVENT_KINDS = st.text(
    alphabet=st.characters(categories=("Ll", "Lu", "Nd")),
    min_size=1,
    max_size=16,
)
JSON_SCALARS = st.one_of(st.none(), st.booleans(), st.integers(), st.text(max_size=32))
EVENT_PAYLOADS = st.dictionaries(
    st.text(min_size=1, max_size=12),
    JSON_SCALARS,
    min_size=0,
    max_size=4,
)
EVENT_INPUTS = st.lists(
    st.tuples(EVENT_KINDS, EVENT_PAYLOADS),
    min_size=1,
    max_size=20,
)
PAGE_LIMITS = st.integers(min_value=0, max_value=12)
PAGE_OFFSETS = st.integers(min_value=0, max_value=12)
TERMINAL_STATUSES = st.sampled_from((
    GenerationRunStatus.SUCCEEDED,
    GenerationRunStatus.FAILED,
    GenerationRunStatus.CANCELLED,
))
ADAPTER_OPERATIONS = st.lists(
    st.one_of(
        st.tuples(st.just("append"), st.tuples(EVENT_KINDS, EVENT_PAYLOADS)),
        st.tuples(st.just("list"), st.none()),
        st.tuples(st.just("terminal"), TERMINAL_STATUSES),
    ),
    min_size=1,
    max_size=18,
)


@dataclasses.dataclass(frozen=True, slots=True)
class AdapterExerciseState:
    """Test state with immutable fields and mutable `appended` contents."""

    store: InMemoryGenerationRunStore
    run_id: uuid.UUID
    appended: list[object]


def _event_multiset(
    events: EventInputs,
) -> collections.Counter[tuple[str, str]]:
    """Return a comparable multiset for event inputs with dict payloads."""
    return collections.Counter((kind, repr(payload)) for kind, payload in events)


def make_generation_run(
    *,
    episode_id: uuid.UUID | None = None,
    status: GenerationRunStatus = GenerationRunStatus.PENDING,
    created_at: dt.datetime = NOW,
) -> GenerationRun:
    """Build a generation run for property tests."""
    return GenerationRun(
        id=uuid.uuid7(),
        episode_id=episode_id or uuid.uuid7(),
        source_bundle_id=uuid.uuid7(),
        actor="editor@example.com",
        status=status,
        current_node=None,
        budget_snapshot={},
        configuration={},
        created_at=created_at,
        updated_at=created_at,
        started_at=None,
        ended_at=None,
        error_message=None,
        quality_mode=QualityMode.DRAFT_WITHOUT_QA,
        qa_status=QaStatus.SKIPPED,
        skip_qa_rationale="No-QA vertical-slice draft.",
    )


@pytest.fixture(scope="module")
def monotonic_time_provider() -> cabc.Callable[[], dt.datetime]:
    """Return a deterministic clock that advances on each call."""
    counter = itertools.count()

    def provide_time() -> dt.datetime:
        return NOW + dt.timedelta(microseconds=next(counter))

    return provide_time


@given(appends=EVENT_INPUTS)
@settings(max_examples=35, deadline=None)
@pytest.mark.asyncio
async def test_concurrent_append_events_are_monotonic_and_gap_free(
    appends: list[tuple[str, dict[str, object]]],
    monotonic_time_provider: cabc.Callable[[], dt.datetime],
) -> None:
    """Concurrent appends to one run should produce a single ordered stream."""
    store = InMemoryGenerationRunStore(time_provider=monotonic_time_provider)
    run = await store.create_run(make_generation_run())

    appended = await asyncio.gather(
        *(
            store.append_event(run.id, kind=kind, payload=payload)
            for kind, payload in appends
        )
    )
    listed = await store.list_events(run.id)

    assert [event.seq for event in listed] == list(range(1, len(appends) + 1)), (
        "Event seq values must be contiguous starting at 1."
    )
    assert all(
        previous.created_at <= current.created_at
        for previous, current in itertools.pairwise(listed)
    ), "Event created_at values must be nondecreasing."
    listed_inputs = tuple((event.kind, event.payload) for event in listed)
    assert _event_multiset(listed_inputs) == _event_multiset(appends), (
        "Listed inputs multiset must match appended inputs."
    )
    assert sorted(event.id for event in appended) == sorted(
        event.id for event in listed
    ), "Listed event ids must match appended event ids."


@given(first_appends=EVENT_INPUTS, second_appends=EVENT_INPUTS)
@settings(max_examples=25, deadline=None)
@pytest.mark.asyncio
async def test_concurrent_append_events_for_different_runs_do_not_share_sequences(
    first_appends: list[tuple[str, dict[str, object]]],
    second_appends: list[tuple[str, dict[str, object]]],
    monotonic_time_provider: cabc.Callable[[], dt.datetime],
) -> None:
    """Each run owns its own event sequence."""
    store = InMemoryGenerationRunStore(time_provider=monotonic_time_provider)
    first_run = await store.create_run(make_generation_run())
    second_run = await store.create_run(make_generation_run())

    await asyncio.gather(
        *(
            store.append_event(first_run.id, kind=kind, payload=payload)
            for kind, payload in first_appends
        ),
        *(
            store.append_event(second_run.id, kind=kind, payload=payload)
            for kind, payload in second_appends
        ),
    )

    first_events = await store.list_events(first_run.id)
    second_events = await store.list_events(second_run.id)

    assert [event.seq for event in first_events] == list(
        range(1, len(first_appends) + 1)
    ), "First run sequence must start at 1 and be gap-free."
    assert [event.seq for event in second_events] == list(
        range(1, len(second_appends) + 1)
    ), "Second run sequence must start at 1 and be gap-free."


@given(idempotency_key=st.text(min_size=1, max_size=24))
@settings(max_examples=30, deadline=None)
@pytest.mark.asyncio
async def test_create_run_idempotency_is_first_write_wins(
    idempotency_key: str,
    monotonic_time_provider: cabc.Callable[[], dt.datetime],
) -> None:
    """A repeated idempotency key should always return the first run."""
    store = InMemoryGenerationRunStore(time_provider=monotonic_time_provider)
    first_run = make_generation_run()
    second_run = make_generation_run()

    created = await store.create_run(first_run, idempotency_key=idempotency_key)
    retried = await store.create_run(second_run, idempotency_key=idempotency_key)

    assert created.id == first_run.id, "First write must be persisted."
    assert retried.id == first_run.id, "Retry must return the first run."
    assert retried.id != second_run.id, "Retry must ignore the supplied run."


@given(terminal_status=TERMINAL_STATUSES)
@settings(max_examples=15, deadline=None)
@pytest.mark.asyncio
async def test_terminal_runs_reject_status_updates_and_events(
    terminal_status: GenerationRunStatus,
    monotonic_time_provider: cabc.Callable[[], dt.datetime],
) -> None:
    """Terminal runs should reject further status updates and event appends."""
    store = InMemoryGenerationRunStore(time_provider=monotonic_time_provider)
    run = await store.create_run(make_generation_run())

    terminal = await store.update_run_status(
        run.id,
        status=terminal_status,
        current_node=None,
        ended_at=NOW,
    )

    assert terminal.status == terminal_status, "Run must enter the terminal state."
    with pytest.raises(RunAlreadyTerminal, match="generation run is already terminal"):
        await store.update_run_status(
            run.id,
            status=GenerationRunStatus.RUNNING,
            current_node="planner",
            ended_at=None,
        )
    with pytest.raises(RunAlreadyTerminal, match="generation run is already terminal"):
        await store.append_event(run.id, kind="node_started", payload={})


@given(
    run_count=st.integers(min_value=1, max_value=10),
    limit=PAGE_LIMITS,
    offset=PAGE_OFFSETS,
)
@settings(max_examples=30, deadline=None)
@pytest.mark.asyncio
async def test_list_runs_pagination_is_stable(
    run_count: int,
    limit: int,
    offset: int,
    monotonic_time_provider: cabc.Callable[[], dt.datetime],
) -> None:
    """Run pagination should be a stable slice of creation order."""
    store = InMemoryGenerationRunStore(time_provider=monotonic_time_provider)
    episode_id = uuid.uuid7()
    created_runs = []
    for index in range(run_count):
        run = make_generation_run(
            episode_id=episode_id,
            created_at=NOW + dt.timedelta(seconds=index),
        )
        created_runs.append(await store.create_run(run))

    listed = await store.list_runs(episode_id, limit=limit, offset=offset)
    expected = tuple(created_runs[offset : offset + limit])

    assert listed == expected, "Run page must match the creation-order slice."


@given(appends=EVENT_INPUTS, limit=PAGE_LIMITS, after_index=PAGE_OFFSETS)
@settings(max_examples=30, deadline=None)
@pytest.mark.asyncio
async def test_list_events_pagination_is_stable(
    appends: list[tuple[str, dict[str, object]]],
    limit: int,
    after_index: int,
    monotonic_time_provider: cabc.Callable[[], dt.datetime],
) -> None:
    """Event pagination should be a stable slice after the sequence cursor."""
    store = InMemoryGenerationRunStore(time_provider=monotonic_time_provider)
    run = await store.create_run(make_generation_run())
    appended = [
        await store.append_event(run.id, kind=kind, payload=payload)
        for kind, payload in appends
    ]
    cursor = min(after_index, len(appended))
    after_seq = event_seq(cursor) if cursor > 0 else None

    listed = await store.list_events(run.id, after_seq=after_seq, limit=limit)
    expected = tuple(appended[cursor : cursor + limit])

    assert listed == expected, "Event page must match the sequence slice."


async def _apply_adapter_operation(
    state: AdapterExerciseState,
    operation_item: AdapterOperation,
    *,
    is_terminal: bool,
    limit: int,
) -> bool:
    """Apply one generated adapter operation and return terminal state."""
    match operation_item:
        case ("append", (kind, payload)):
            if is_terminal:
                with pytest.raises(
                    RunAlreadyTerminal,
                    match="generation run is already terminal",
                ):
                    await state.store.append_event(
                        state.run_id,
                        kind=kind,
                        payload=payload,
                    )
                return is_terminal
            state.appended.append(
                await state.store.append_event(
                    state.run_id,
                    kind=kind,
                    payload=payload,
                )
            )
            return is_terminal
        case ("terminal", status):
            status = typ.cast("GenerationRunStatus", status)
            if is_terminal:
                with pytest.raises(
                    RunAlreadyTerminal,
                    match="generation run is already terminal",
                ):
                    await state.store.update_run_status(
                        state.run_id,
                        status=status,
                        current_node=None,
                        ended_at=NOW,
                    )
                return is_terminal
            await state.store.update_run_status(
                state.run_id,
                status=status,
                current_node=None,
                ended_at=NOW,
            )
            return True
        case ("list", None):
            listed = await state.store.list_events(state.run_id, limit=limit)
            assert listed == tuple(state.appended[:limit]), (
                "Listed events must preserve adapter sequence order."
            )
            return is_terminal
    msg = f"Unknown adapter operation: {operation_item!r}"
    raise AssertionError(msg)


@given(
    idempotency_key=st.text(min_size=1, max_size=24),
    operations=ADAPTER_OPERATIONS,
    limit=PAGE_LIMITS,
)
@settings(max_examples=35, deadline=None)
@pytest.mark.asyncio
async def test_adapter_invariants_hold_across_generated_operation_sequences(
    idempotency_key: str,
    operations: list[AdapterOperation],
    limit: int,
    monotonic_time_provider: cabc.Callable[[], dt.datetime],
) -> None:
    """Generated adapter operation sequences should preserve core invariants."""
    store = InMemoryGenerationRunStore(time_provider=monotonic_time_provider)
    run = await store.create_run(
        make_generation_run(),
        idempotency_key=idempotency_key,
    )
    retried = await store.create_run(
        make_generation_run(),
        idempotency_key=idempotency_key,
    )
    state = AdapterExerciseState(store=store, run_id=run.id, appended=[])
    is_terminal = False

    assert retried.id == run.id, "Idempotency retry must return first run."

    for operation_item in operations:
        is_terminal = await _apply_adapter_operation(
            state,
            operation_item,
            is_terminal=is_terminal,
            limit=limit,
        )

    listed = await store.list_events(run.id)
    assert [event.seq for event in listed] == list(range(1, len(state.appended) + 1)), (
        "Generated operation sequences must leave gap-free event sequences."
    )
    for after_index in range(len(state.appended) + 1):
        after_seq = event_seq(after_index) if after_index else None
        page = await store.list_events(run.id, after_seq=after_seq, limit=limit)
        assert page == tuple(state.appended[after_index : after_index + limit]), (
            "Event cursor pages must match the appended event slice."
        )
