"""Property tests for source-intake idempotency invariants."""

import dataclasses as dc
import datetime as dt
import uuid

import pytest
from hypothesis import given
from hypothesis import strategies as st

from episodic.canonical.idempotency import (
    Acquired,
    Conflict,
    IdempotencyAcquireRequest,
    IdempotencyRecord,
    IdempotencyState,
    InFlight,
    Replay,
)
from episodic.canonical.upload_protocols import IdempotencyStore


@dc.dataclass
class _InMemoryIdempotencyStore(IdempotencyStore):
    """In-memory store mirroring the domain idempotency state machine."""

    records: dict[tuple[str | None, str, str], IdempotencyRecord] = dc.field(
        default_factory=dict
    )

    async def acquire(
        self,
        *,
        request: IdempotencyAcquireRequest,
    ) -> Acquired | Replay | Conflict | InFlight:
        """Acquire or inspect a keyed idempotency record."""
        key = (request.principal_id, request.operation, request.idempotency_key)
        now = dt.datetime.now(dt.UTC)
        existing = self.records.get(key)
        if existing is None:
            record = IdempotencyRecord(
                id=uuid.uuid4(),
                principal_id=request.principal_id,
                operation=request.operation,
                idempotency_key=request.idempotency_key,
                body_hash=request.body_hash,
                state=IdempotencyState.IN_FLIGHT,
                serialised_outcome=None,
                expires_at=request.expires_at,
                created_at=now,
                updated_at=now,
            )
            self.records[key] = record
            return Acquired(record.id)
        if existing.body_hash != request.body_hash:
            return Conflict(existing.id)
        if existing.state is IdempotencyState.IN_FLIGHT:
            return InFlight(existing.id)
        if existing.serialised_outcome is None:  # pragma: no cover - defensive
            msg = "completed in-memory records require an outcome."
            raise AssertionError(msg)
        return Replay(existing.serialised_outcome)

    async def complete(
        self,
        *,
        record_id: uuid.UUID,
        serialised_outcome: bytes,
    ) -> None:
        """Complete a record by identifier."""
        for key, record in self.records.items():
            if record.id == record_id:
                self.records[key] = dc.replace(
                    record,
                    state=IdempotencyState.COMPLETED,
                    serialised_outcome=serialised_outcome,
                    updated_at=dt.datetime.now(dt.UTC),
                )
                return
        msg = f"unknown idempotency record: {record_id}"
        raise LookupError(msg)

    async def lookup(
        self,
        *,
        principal_id: str | None,
        operation: str,
        idempotency_key: str,
    ) -> IdempotencyRecord | None:
        """Fetch a stored idempotency record by logical key."""
        return self.records.get((principal_id, operation, idempotency_key))


@pytest.mark.asyncio
@pytest.mark.hypothesis
@given(
    body_hash=st.text(min_size=1).filter(str.strip),
    replay_payload=st.binary(min_size=1),
)
async def test_identical_body_for_key_replays_one_completed_resource(
    body_hash: str,
    replay_payload: bytes,
) -> None:
    """Property: identical bodies for a key converge on one completed record."""
    store = _InMemoryIdempotencyStore()
    expires_at = dt.datetime.now(dt.UTC) + dt.timedelta(hours=1)

    first = await store.acquire(
        request=IdempotencyAcquireRequest(
            principal_id="principal",
            operation="upload.create",
            idempotency_key="same-key",
            body_hash=body_hash,
            expires_at=expires_at,
        ),
    )
    assert isinstance(first, Acquired)
    await store.complete(record_id=first.record_id, serialised_outcome=replay_payload)

    second = await store.acquire(
        request=IdempotencyAcquireRequest(
            principal_id="principal",
            operation="upload.create",
            idempotency_key="same-key",
            body_hash=body_hash,
            expires_at=expires_at,
        ),
    )

    assert isinstance(second, Replay)
    assert second.serialised_outcome == replay_payload
    assert len(store.records) == 1


@pytest.mark.asyncio
@pytest.mark.hypothesis
@given(
    first_hash=st.text(min_size=1).filter(str.strip),
    second_hash=st.text(min_size=1).filter(str.strip),
)
async def test_different_body_for_key_conflicts(
    first_hash: str,
    second_hash: str,
) -> None:
    """Property: reusing a key with a different body hash conflicts."""
    if first_hash == second_hash:
        second_hash = f"{second_hash}:different"
    store = _InMemoryIdempotencyStore()
    expires_at = dt.datetime.now(dt.UTC) + dt.timedelta(hours=1)

    first = await store.acquire(
        request=IdempotencyAcquireRequest(
            principal_id="principal",
            operation="upload.create",
            idempotency_key="same-key",
            body_hash=first_hash,
            expires_at=expires_at,
        ),
    )
    assert isinstance(first, Acquired)

    second = await store.acquire(
        request=IdempotencyAcquireRequest(
            principal_id="principal",
            operation="upload.create",
            idempotency_key="same-key",
            body_hash=second_hash,
            expires_at=expires_at,
        ),
    )

    assert isinstance(second, Conflict)
    assert second.record_id == first.record_id
    assert len(store.records) == 1


@pytest.mark.asyncio
@pytest.mark.hypothesis
@given(
    principal_a=st.text(min_size=1).filter(str.strip),
    principal_b=st.text(min_size=1).filter(str.strip),
    body_hash=st.text(min_size=1).filter(str.strip),
)
async def test_same_key_is_scoped_by_authenticated_principal(
    principal_a: str,
    principal_b: str,
    body_hash: str,
) -> None:
    """Property: equal keys and bodies remain isolated across principals."""
    if principal_a == principal_b:
        principal_b = f"{principal_b}:other"
    store = _InMemoryIdempotencyStore()
    expires_at = dt.datetime.now(dt.UTC) + dt.timedelta(hours=1)

    first = await store.acquire(
        request=IdempotencyAcquireRequest(
            principal_id=principal_a,
            operation="upload.create",
            idempotency_key="same-key",
            body_hash=body_hash,
            expires_at=expires_at,
        ),
    )
    second = await store.acquire(
        request=IdempotencyAcquireRequest(
            principal_id=principal_b,
            operation="upload.create",
            idempotency_key="same-key",
            body_hash=body_hash,
            expires_at=expires_at,
        ),
    )

    assert isinstance(first, Acquired)
    assert isinstance(second, Acquired)
    assert first.record_id != second.record_id
    assert len(store.records) == 2
