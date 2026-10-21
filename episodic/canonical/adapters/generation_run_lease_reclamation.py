"""In-memory lease reclamation for the generation-run reference adapter.

The in-memory adapter cannot honestly reclaim an expired lease, and the whole
point of the module is to say so in one place rather than let the composite
store grow past the project's file-size ceiling.

``GenerationRun`` has no lease field. ``lease_expires_at`` is a storage-only
column: :meth:`InMemoryGenerationRunStore.claim_run_for_execution` logs it for
protocol parity and discards it, and no in-memory consumer reads lease state.
So no in-memory run is ever observably expired, and returning ``()`` is the only
truthful answer available.

That emptiness is a divergence from the SQL adapter, not an implementation of
it. A shared contract suite must therefore **not** drive
``fail_expired_leases`` against both adapters and treat agreement as evidence:
both would return ``()`` for different reasons, and the suite would certify a
no-op it never exercised.
"""

import typing as typ

if typ.TYPE_CHECKING:
    import datetime as dt

    from episodic.canonical.domain import GenerationRun


class InMemoryGenerationRunLeaseReclamationMixin:
    """Lease reclamation for an adapter that cannot store a lease."""

    async def fail_expired_leases(  # ruff: ignore[no-self-use] - must match the composite port's instance method.
        self,
        *,
        now: dt.datetime,
        limit: int = 100,
    ) -> tuple[GenerationRun, ...]:
        """Reclaim nothing, because this adapter cannot store a lease.

        Necessarily a no-op returning ``()``: ``GenerationRun`` has no lease
        field, so this adapter retains no ``lease_expires_at`` to compare
        against ``now`` and can never observe an expired lease. Implementations
        that do persist a lease must not use this behaviour as their contract.

        Parameters
        ----------
        now : dt.datetime
            Instant the expiry predicate would use. Accepted for protocol
            parity and ignored.
        limit : int
            Maximum batch size. Accepted for protocol parity and ignored.

        Returns
        -------
        tuple[GenerationRun, ...]
            Always empty, for every input.
        """
        return ()
