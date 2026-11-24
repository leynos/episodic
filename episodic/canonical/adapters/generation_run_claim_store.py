"""Claim bookkeeping for the in-memory generation-run store.

The reference adapter keeps claim tokens in a side map because
``GenerationRun`` carries no token field. That bookkeeping is separated from
the store's read and event paths so each module keeps one responsibility and
stays within the repository's module-length limit.
"""

import collections.abc as cabc
import dataclasses as dc
import typing as typ
import uuid

from episodic.canonical.domain import GenerationRun, GenerationRunStatus
from episodic.logging import log_event as _log_event

if typ.TYPE_CHECKING:
    from episodic.canonical.generation_claim import ExecutionClaim


@dc.dataclass(slots=True)
class InMemoryClaimTokens(cabc.Mapping[uuid.UUID, uuid.UUID]):
    """The claim token each run holds, keyed by run id.

    A run absent from the mapping holds no claim, which the terminal-claim
    rule treats as having no owner to check.

    Attributes
    ----------
    tokens : dict[uuid.UUID, uuid.UUID]
        Stored proof per run.
    """

    tokens: dict[uuid.UUID, uuid.UUID] = dc.field(default_factory=dict)

    def record(self, run_id: uuid.UUID, claim: ExecutionClaim) -> None:
        """Retain the claim's proof when it carries one."""
        if claim.claim_token is not None:
            self.tokens[run_id] = claim.claim_token

    def __getitem__(self, run_id: uuid.UUID) -> uuid.UUID:
        """Return a run's stored proof, raising ``KeyError`` when unclaimed."""
        return self.tokens[run_id]

    def __iter__(self) -> cabc.Iterator[uuid.UUID]:
        """Iterate the runs that hold a claim."""
        return iter(self.tokens)

    def __len__(self) -> int:
        """Return how many runs hold a claim."""
        return len(self.tokens)


def claimed_run(
    run: GenerationRun,
    claim: ExecutionClaim,
    *,
    updated_at: object,
) -> GenerationRun:
    """Return the run transitioned to running by a won claim.

    Parameters
    ----------
    run : GenerationRun
        The pending run that was claimed.
    claim : ExecutionClaim
        The winning claim; its node and start instant are recorded.
    updated_at : object
        Timestamp the adapter's clock reports for this write.

    Returns
    -------
    GenerationRun
        The run in its ``running`` state.
    """
    return dc.replace(
        run,
        status=GenerationRunStatus.RUNNING,
        current_node=claim.current_node,
        started_at=claim.started_at,
        updated_at=typ.cast("typ.Any", updated_at),
    )


def log_claim(
    run_id: uuid.UUID,
    claim: ExecutionClaim,
) -> None:
    """Log a won claim, including its lease when it has one."""
    _log_event(
        "info",
        "generation_run_store.claim_run",
        run_id=str(run_id),
        current_node=claim.current_node,
        lease_expires_at=claim.lease_expires_at.isoformat()
        if claim.lease_expires_at is not None
        else None,
    )
