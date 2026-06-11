"""Domain idempotency entities and outcomes."""

import dataclasses as dc
import enum
import typing as typ

if typ.TYPE_CHECKING:
    import datetime as dt
    import uuid


class IdempotencyState(enum.StrEnum):
    """Stored idempotency record states."""

    IN_FLIGHT = "in_flight"
    COMPLETED = "completed"


def _require_non_empty_string(value: str, field_name: str) -> None:
    """Raise ValueError when *value* is blank after stripping whitespace."""
    if not value.strip():
        msg = f"{field_name} must be a non-empty string."
        raise ValueError(msg)


def _require_completed_has_outcome(
    state: IdempotencyState, serialised_outcome: bytes | None
) -> None:
    """Raise ValueError when a completed record lacks a serialised outcome."""
    if state is IdempotencyState.COMPLETED and serialised_outcome is None:
        msg = "completed idempotency records require serialised_outcome."
        raise ValueError(msg)


def _validate_idempotency_key_fields(
    operation: str, idempotency_key: str, body_hash: str
) -> None:
    """Validate the three shared idempotency key string fields."""
    _require_non_empty_string(operation, "operation")
    _require_non_empty_string(idempotency_key, "idempotency_key")
    _require_non_empty_string(body_hash, "body_hash")


@dc.dataclass(frozen=True, slots=True)
class IdempotencyRecord:
    """Stored request fingerprint and opaque replay payload."""

    id: uuid.UUID
    principal_id: str | None
    operation: str
    idempotency_key: str
    body_hash: str
    state: IdempotencyState
    serialised_outcome: bytes | None
    expires_at: dt.datetime
    created_at: dt.datetime
    updated_at: dt.datetime

    def __post_init__(self) -> None:
        """Validate domain-only idempotency state."""
        _validate_idempotency_key_fields(
            self.operation, self.idempotency_key, self.body_hash
        )
        _require_completed_has_outcome(self.state, self.serialised_outcome)


@dc.dataclass(frozen=True, slots=True)
class IdempotencyAcquireRequest:
    """Input required to acquire a retryable side-effect record."""

    principal_id: str | None
    operation: str
    idempotency_key: str
    body_hash: str
    expires_at: dt.datetime

    def __post_init__(self) -> None:
        """Validate logical idempotency-key input."""
        _validate_idempotency_key_fields(
            self.operation, self.idempotency_key, self.body_hash
        )


@dc.dataclass(frozen=True, slots=True)
class Acquired:
    """Outcome indicating the caller owns the in-flight record."""

    record_id: uuid.UUID


@dc.dataclass(frozen=True, slots=True)
class Replay:
    """Outcome carrying an opaque completed payload for adapter replay."""

    serialised_outcome: bytes


@dc.dataclass(frozen=True, slots=True)
class Conflict:
    """Outcome indicating the same key was used with a different body hash."""

    record_id: uuid.UUID


@dc.dataclass(frozen=True, slots=True)
class InFlight:
    """Outcome indicating an identical request is still being processed."""

    record_id: uuid.UUID


type IdempotencyOutcome = Acquired | Replay | Conflict | InFlight
