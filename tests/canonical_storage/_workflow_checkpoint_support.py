"""Shared test doubles for workflow checkpoint store tests.

Hosts the deterministic ``RecordingMetrics`` and ``StepClock`` fakes used by
``test_workflow_checkpoints.py`` and the ``make_checkpoint`` fixture builder, so
the test module stays focused on behaviour rather than infrastructure.
"""

import dataclasses
import typing as typ
import uuid
from unittest import mock

from sqlalchemy.exc import IntegrityError

from episodic.orchestration import WorkflowCheckpoint

if typ.TYPE_CHECKING:
    import collections.abc as cabc


def make_checkpoint(
    *,
    checkpoint_id: str | None = None,
    idempotency_key: str | None = None,
) -> WorkflowCheckpoint:
    """Return a deterministic checkpoint fixture."""
    return WorkflowCheckpoint(
        checkpoint_id=checkpoint_id or str(uuid.uuid4()),
        workflow_id="corr-storage",
        workflow_type="generation_orchestration",
        step_name="execute",
        idempotency_key=(
            idempotency_key
            or "corr-storage:generation_orchestration:execute:action-1:0"
        ),
        payload={
            "request": {"correlation_id": "corr-storage"},
            "planner_result": {"plan": {"steps": []}},
        },
    )


class RecordingMetrics:
    """Capture checkpoint metrics for adapter assertions."""

    def __init__(self) -> None:
        self.counters: list[tuple[str, dict[str, str]]] = []
        self.latencies: list[tuple[str, float, dict[str, str]]] = []

    def increment_counter(
        self,
        name: str,
        *,
        labels: cabc.Mapping[str, str],
    ) -> None:
        """Record a counter increment."""
        self.counters.append((name, dict(labels)))

    def observe_latency_ms(
        self,
        name: str,
        value: float,
        *,
        labels: cabc.Mapping[str, str],
    ) -> None:
        """Record a latency observation."""
        self.latencies.append((name, value, dict(labels)))

    def as_snapshot(self) -> dict[str, list[dict[str, object]]]:
        """Return the recorded metrics in a stable, snapshot-friendly form.

        Counter and latency tuples flatten into ordered dictionaries so syrupy's
        ``.ambr`` output stays deterministic and human-readable. ``StepClock``
        already advances by exactly 1 ms per call, so the latency values appear
        verbatim in the snapshot and need no further redaction.
        """
        return {
            "counters": [
                {"name": name, "labels": labels} for name, labels in self.counters
            ],
            "latencies": [
                {"name": name, "value": value, "labels": labels}
                for name, value, labels in self.latencies
            ],
        }


class StepClock:
    """Deterministic monotonic clock for metric latency assertions."""

    def __init__(self) -> None:
        self._seconds = 0.0

    def monotonic_seconds(self) -> float:
        """Return a timestamp that advances by 1 ms on each call."""
        self._seconds += 0.001
        return self._seconds


def make_integrity_error() -> IntegrityError:
    """Return an IntegrityError mirroring a duplicate idempotency-key rejection."""
    return IntegrityError(
        statement="INSERT INTO workflow_checkpoints ...",
        params={},
        orig=Exception("UNIQUE constraint failed: idempotency_key"),
    )


@dataclasses.dataclass(frozen=True, slots=True)
class VanishingConflictSession:
    """Carries the session and empty-result mocks for the recovery-failure path."""

    session: mock.MagicMock
    empty_result: mock.MagicMock


def make_vanishing_conflict_session() -> VanishingConflictSession:
    """Return mock session and result for the recovery-failure path.

    ``flush()`` raises an ``IntegrityError`` (duplicate idempotency key) and
    the subsequent ``execute()`` returns no row, simulating the conflicting
    checkpoint vanishing before recovery can read it back.
    """
    savepoint_cm = mock.MagicMock()
    savepoint_cm.__aenter__ = mock.AsyncMock(return_value=savepoint_cm)
    savepoint_cm.__aexit__ = mock.AsyncMock(return_value=None)

    empty_result = mock.MagicMock()
    empty_result.scalar_one_or_none.return_value = None

    session = mock.MagicMock()
    session.begin_nested = mock.MagicMock(return_value=savepoint_cm)
    session.add = mock.MagicMock()
    session.flush = mock.AsyncMock(side_effect=make_integrity_error())
    session.execute = mock.AsyncMock(return_value=empty_result)
    return VanishingConflictSession(session=session, empty_result=empty_result)
