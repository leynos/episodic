"""Values for one generation-run execution claim.

The claim is a single immutable command: the node, the start and lease times,
and the unique proof that lets a lost commit acknowledgement be reconciled.
"""

import dataclasses as dc
import typing as typ

if typ.TYPE_CHECKING:
    import datetime as dt
    import uuid


@dc.dataclass(frozen=True, slots=True)
class ExecutionClaim:
    """One pending-to-running claim attempt.

    Attributes
    ----------
    current_node : str | None
        Worker node that would own the claim.
    started_at : dt.datetime
        Timestamp at which execution would start.
    lease_expires_at : dt.datetime | None
        Optional lease expiry recorded with the claim.
    claim_token : uuid.UUID | None
        Unique proof stored with the claim, used to reconcile a lost commit
        acknowledgement.
    """

    current_node: str | None
    started_at: dt.datetime
    lease_expires_at: dt.datetime | None
    claim_token: uuid.UUID | None = None
