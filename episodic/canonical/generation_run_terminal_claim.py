"""The terminal-claim rule shared by both generation-run stores.

A terminal write must name the claim that owns the run. The SQL adapter holds
the stored token on its row and the reference adapter keeps it in a side map,
but the decision itself is identical, so it lives here once.

A run that never stored a claim has no owner to check: a launch failure before
the first claim, and a reclamation candidate created outside a claim, are both
legitimate internal writers. Only a run that *does* hold a claim is fenced.
"""

import typing as typ

from episodic.canonical.generation_run_errors import RunClaimMismatch

if typ.TYPE_CHECKING:
    import uuid

    from episodic.canonical.generation_run_ports import GenerationRunStatusUpdate


def require_terminal_claim(
    run_id: uuid.UUID,
    update: GenerationRunStatusUpdate,
    stored_token: uuid.UUID | None,
) -> None:
    """Refuse a terminal write that does not name the run's stored claim.

    Parameters
    ----------
    run_id : uuid.UUID
        Identifier of the run being terminated.
    update : GenerationRunStatusUpdate
        The requested transition. A non-terminal transition is not checked.
    stored_token : uuid.UUID | None
        The run's durable claim token, read under the store's lock, or
        ``None`` when the run holds no claim.

    Raises
    ------
    RunClaimMismatch
        If the transition is terminal, the run holds a claim, and the update
        names a different token (including none at all).
    """
    if not update.status.is_terminal():
        return
    if stored_token is None:
        return
    if update.claim_token != stored_token:
        raise RunClaimMismatch(run_id)
