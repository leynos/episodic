"""Generated state-machine invariants for the in-memory generation-run store."""

import datetime as dt
import itertools

import hypothesis.strategies as st
import pytest
from hypothesis import given, settings

from episodic.canonical.adapters.generation_runs import InMemoryGenerationRunStore
from episodic.canonical.domain import GenerationRunStatus
from episodic.canonical.generation_run_errors import RunAlreadyTerminal
from episodic.canonical.generation_run_ports import GenerationRunStatusUpdate, event_seq
from tests.test_generation_run_properties import (
    ADAPTER_OPERATIONS,
    NOW,
    PAGE_LIMITS,
    AdapterExerciseState,
    AdapterOperation,
    make_generation_run,
)


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
        case ("terminal", GenerationRunStatus() as status):
            if is_terminal:
                with pytest.raises(
                    RunAlreadyTerminal,
                    match="generation run is already terminal",
                ):
                    await state.store.update_run_status(
                        state.run_id,
                        update=GenerationRunStatusUpdate(
                            status=status,
                            current_node=None,
                            ended_at=NOW,
                        ),
                    )
                return is_terminal
            await state.store.update_run_status(
                state.run_id,
                update=GenerationRunStatusUpdate(
                    status=status,
                    current_node=None,
                    ended_at=NOW,
                ),
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
) -> None:
    """Generated adapter operation sequences should preserve core invariants."""
    counter = itertools.count()

    def monotonic_time_provider() -> dt.datetime:
        return NOW + dt.timedelta(microseconds=next(counter))

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
