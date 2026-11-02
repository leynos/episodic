"""Refusal events shared by the review-checkpoint adapter's terminal routes.

Two paths can discover an already-terminal checkpoint: the domain transition
rejects it up front, or the compare-and-set update matches no row because a
concurrent writer got there first. Both must emit the same event, so the
emission lives here instead of being written out twice; the exception it raises
is the same one either route ends in.
"""

import typing as typ

from episodic.canonical.generation_run_errors import CheckpointAlreadyTerminal
from episodic.logging import log_event as _log_event

if typ.TYPE_CHECKING:
    from .review_checkpoint_models import ReviewCheckpointRecord


def refuse_already_terminal(
    event: str,
    record: ReviewCheckpointRecord,
    fields: dict[str, str],
) -> typ.NoReturn:
    """Report the refused transition, then raise :class:`CheckpointAlreadyTerminal`.

    Parameters
    ----------
    event : str
        Operation that was refused, such as ``respond_checkpoint``. It names
        the event so a retry storm on one transition is distinguishable from
        another's.
    record : ReviewCheckpointRecord
        Stored row that was already in a terminal state.
    fields : dict of str to str
        Further context describing the refused request.

    Raises
    ------
    CheckpointAlreadyTerminal
        Always: the stored checkpoint had already left the ``created`` state.
    """
    _log_event(
        "warning",
        f"sql_review_checkpoint_store.{event}_already_terminal",
        checkpoint_id=str(record.id),
        run_id=str(record.generation_run_id),
        status=record.status.value,
        **fields,
    )
    raise CheckpointAlreadyTerminal(record.id)
