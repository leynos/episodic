"""Port for reclaiming generation runs whose execution lease expired.

Lease reclamation is storage-shaped behaviour: ``lease_expires_at`` is a
storage column with no ``GenerationRun`` counterpart, so only a durable adapter
can implement it. It is nevertheless a *port* rather than an adapter detail
because the reclamation transaction also appends a ``run.failed`` event, which
is `GenerationEventLog` behaviour. That is why the method lives on the composite
`GenerationRunPort` and not on the narrow `GenerationRunRepository`: putting it
on the repository would oblige every future implementer of that port to also be
an event log, the coupling ADR-015 removed.

The primitive is deliberately not a worker. It performs one transaction with a
finite state partition, so a caller decides when to run it and how often; the
scheduling, at-most-once semantics, and operational ownership a background
reaper needs are outside this contract.
"""

import typing as typ

if typ.TYPE_CHECKING:
    import datetime as dt

    from .domain import GenerationRun


def lease_reclamation_limit(limit: int) -> int:
    """Validate and return a lease-reclamation batch limit.

    Parameters
    ----------
    limit : int
        Caller-supplied maximum batch size.

    Returns
    -------
    int
        The validated limit, unchanged.

    Raises
    ------
    ValueError
        If ``limit`` is not positive. A zero or negative limit cannot be
        honoured without silently reclaiming either nothing or everything, so
        adapters reject it rather than choosing a behaviour for the caller.
    """
    if limit < 1:
        msg = "limit must be a positive integer."
        raise ValueError(msg)
    return limit


@typ.runtime_checkable
class GenerationRunLeaseReclamationPort(typ.Protocol):
    """Reclaim generation runs abandoned by a worker holding an expired lease."""

    async def fail_expired_leases(
        self,
        *,
        now: dt.datetime,
        limit: int = 100,
    ) -> tuple[GenerationRun, ...]:
        """Fail runs whose execution lease expired at or before ``now``.

        Parameters
        ----------
        now : dt.datetime
            The single instant this call reasons about. It bounds the expiry
            predicate *and* is the value written to ``ended_at``,
            ``updated_at``, and the ``run.failed`` event's ``occurred_at``, so
            one call never records two different "nows". Pass the same instant
            a caller already used to decide that a backlog exists.
        limit : int
            Maximum number of runs to reclaim in this call. Must be positive.
            A call that returns exactly ``limit`` runs has more work waiting, so
            a caller draining a backlog re-invokes until an empty tuple comes
            back.

        Returns
        -------
        tuple[GenerationRun, ...]
            The reclaimed runs in their post-transition ``failed`` state, in
            the order they were drained: ascending ``(lease_expires_at, id)``.
            The ordering is a total order, so repeated re-invocations against
            one backlog produce the same sequence of batches.

        Raises
        ------
        ValueError
            If ``limit`` is not positive.

        Notes
        -----
        A run is reclaimed only when all three hold: its status is ``running``,
        its ``lease_expires_at`` is non-null and at or before ``now``, and it
        has **no checkpoint in ``created``**. The checkpoint clause is load
        bearing: a run suspended at a human-review checkpoint keeps its lease
        expired while it waits for a reviewer, and reclaiming it would fail the
        very runs the review mechanism exists to protect.

        Each reclaimed run receives exactly one ``run.failed`` event carrying
        ``error_category`` and ``error_message``, in the same transaction as
        the status change. Implementations must append the event **before**
        applying the terminal status: a run's event stream closes when the run
        ends, so an append attempted after the status update fails. The reverse
        order type-checks, so any implementer must satisfy this ordering by
        test rather than by inspection.

        A reclaimed run ends with ``current_node`` cleared and ``ended_at`` set
        to ``now``, matching every other terminal transition.
        """
        raise NotImplementedError
