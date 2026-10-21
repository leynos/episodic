"""Metric emission for the durable review-checkpoint adapter.

The metric names and their emission live here so the open-checkpoint gauge has
one policy in one place: it is written at *both* ends of a checkpoint's life,
when the checkpoint is created and when it is resolved. Every other emitter in
this package writes one metric at one point, so the gauge's extra update point
is the thing a reader has to be told about -- emitting it only where a
checkpoint is resolved reports the open count of whichever run resolved last,
which cannot show checkpoints accumulating.
"""

import typing as typ

if typ.TYPE_CHECKING:
    from episodic.canonical.domain import CheckpointStatus
    from episodic.observability import ValueMetricsPort

_METRIC_CREATED = "review_checkpoint_created_total"
_METRIC_RESOLVED = "review_checkpoint_resolved_total"
_METRIC_OPEN = "review_checkpoint_open_gauge"
_METRIC_TERMINAL_CONFLICT = "review_checkpoint_terminal_conflict_total"


def record_checkpoint_created(
    metrics: ValueMetricsPort,
    *,
    open_count: float,
) -> None:
    """Count a creation and observe the run's remaining open checkpoints.

    Parameters
    ----------
    metrics : ValueMetricsPort
        Sink to write to.
    open_count : float
        Unresolved checkpoints the new checkpoint's run now holds.
    """
    metrics.increment_counter(_METRIC_CREATED, labels={})
    metrics.observe_value(_METRIC_OPEN, open_count, labels={})


def record_checkpoint_resolved(
    metrics: ValueMetricsPort,
    status: CheckpointStatus,
    *,
    open_count: float,
) -> None:
    """Count a resolution by resulting status and observe the shared gauge.

    Parameters
    ----------
    metrics : ValueMetricsPort
        Sink to write to.
    status : CheckpointStatus
        Terminal status the checkpoint reached. Emitted under the ``status``
        label rather than ``action``: the value is a lifecycle state, while an
        *action* in this package is the distinct ``CheckpointAction`` a
        reviewer response carries.
    open_count : float
        Unresolved checkpoints the resolved checkpoint's run still holds.
    """
    metrics.increment_counter(_METRIC_RESOLVED, labels={"status": status.value})
    metrics.observe_value(_METRIC_OPEN, open_count, labels={})


def record_terminal_conflict(metrics: ValueMetricsPort) -> None:
    """Count a compare-and-set transition that lost to another writer."""
    metrics.increment_counter(_METRIC_TERMINAL_CONFLICT, labels={})
