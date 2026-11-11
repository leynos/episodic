"""Ports and errors for persisted pricing-snapshot access.

`CostRecorder` persists the snapshot it prices from and later reads that
stored row, so a pinned run keeps its rates after the source rate card is
edited or removed. This module owns the repository port and its errors; the
snapshot value object itself lives in `episodic.cost.pricing_snapshot`.

Examples
--------
Persist once, then price from the stored row:

>>> ensured = await snapshots.ensure(snapshot)
>>> stored = await snapshots.get(ensured.pricing_snapshot_id)
"""

import dataclasses as dc
import enum
import typing as typ

from episodic.cost.primitives import CostAccountingError, PricingSnapshotId

if typ.TYPE_CHECKING:
    from episodic.cost.pricing_snapshot import PricingSnapshot


class SnapshotEnsureOutcome(enum.StrEnum):
    """Outcome of persisting one immutable pricing snapshot."""

    PERSISTED = "persisted"
    REUSED = "reused"


@dc.dataclass(frozen=True, slots=True)
class EnsuredPricingSnapshot:
    """Identifier and persistence outcome for one ensured snapshot.

    Attributes
    ----------
    pricing_snapshot_id : PricingSnapshotId
        Identifier that ledger rows and run pins must reference.
    outcome : SnapshotEnsureOutcome
        Whether the stored row was inserted or already existed.
    """

    pricing_snapshot_id: PricingSnapshotId
    outcome: SnapshotEnsureOutcome


class PricingSnapshotError(CostAccountingError):
    """Base error for pricing-snapshot persistence and reads."""


class PricingSnapshotNotFoundError(PricingSnapshotError, LookupError):
    """Raised when a pinned snapshot identifier has no stored row."""


class PricingSnapshotIntegrityError(PricingSnapshotError):
    """Raised when stored pricing content cannot be trusted.

    Either the stored row no longer hashes to its recorded content hash, or a
    run pin names a snapshot that prices a different subject than the call
    being recorded.
    """


@typ.runtime_checkable
class PricingSnapshotRepository(typ.Protocol):
    """Port for persisting and reading immutable pricing snapshots."""

    async def ensure(self, snapshot: PricingSnapshot) -> EnsuredPricingSnapshot:
        """Persist a snapshot and return the identifier stored for it.

        Parameters
        ----------
        snapshot : PricingSnapshot
            Immutable pricing input to persist.

        Returns
        -------
        EnsuredPricingSnapshot
            Stored identifier and whether this call inserted the row.

        Raises
        ------
        PricingSnapshotIntegrityError
            Raised when the insert conflicts without a row for the same
            content hash. A match against an existing row is a successful
            reuse, not an integrity failure.

        Notes
        -----
        Repeated calls for the same snapshot identity reuse the stored row
        unchanged; persistence never rewrites existing values.
        """
        raise NotImplementedError

    async def get(self, pricing_snapshot_id: PricingSnapshotId) -> PricingSnapshot:
        """Return one stored snapshot by identifier.

        Parameters
        ----------
        pricing_snapshot_id : PricingSnapshotId
            Identifier pinned to a workflow run or referenced by a ledger row.

        Returns
        -------
        PricingSnapshot
            Snapshot built from the stored row.

        Raises
        ------
        PricingSnapshotNotFoundError
            Raised when no row is stored for the identifier.
        PricingSnapshotIntegrityError
            Raised when the stored row no longer hashes to its recorded
            content hash.
        """
        raise NotImplementedError
