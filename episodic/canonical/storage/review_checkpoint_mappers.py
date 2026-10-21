"""Record-to-domain mappings for durable review checkpoints.

The record's resolving column is ``resolved_at`` and the domain field is
``responded_at``, because a checkpoint leaves ``created`` by responding, timing
out, or being cancelled, and only the first of those has a responder. The
mappers own that translation so no adapter has to know it.
"""

import typing as typ

from episodic.canonical.domain import Checkpoint

from .review_checkpoint_models import ReviewCheckpointRecord


def _options_to_tuple(raw: object) -> tuple[str, ...]:
    """Return a stored JSON array as an ordered tuple of strings.

    The database CHECK constraint already rejects a non-array, so the shape is
    re-validated here only because a violation reaching this point would
    otherwise surface as an opaque failure inside the domain constructor.

    Returns
    -------
    tuple of str
        The stored options in their persisted order.

    Raises
    ------
    TypeError
        If ``raw`` is not a list, or holds a non-string element.
    """
    if not isinstance(raw, list):
        msg = f"checkpoint options must be a JSON array. Got {raw!r}."
        raise TypeError(msg)
    items = typ.cast("list[object]", raw)
    if any(not isinstance(item, str) for item in items):
        msg = f"checkpoint options must hold only strings. Got {items!r}."
        raise TypeError(msg)
    return tuple(typ.cast("list[str]", raw))


def checkpoint_from_record(record: ReviewCheckpointRecord) -> Checkpoint:
    """Map a review-checkpoint record to a domain entity.

    Returns
    -------
    Checkpoint
        The domain entity the record currently holds.
    """
    return Checkpoint(
        id=record.id,
        generation_run_id=record.generation_run_id,
        node=record.node,
        prompt=record.prompt,
        options=_options_to_tuple(record.options),
        status=record.status,
        created_at=record.created_at,
        responded_at=record.resolved_at,
        responded_by=record.responded_by,
        response_action=record.response_action,
        response_payload=record.response_payload,
    )


def checkpoint_to_record(checkpoint: Checkpoint) -> ReviewCheckpointRecord:
    """Map a checkpoint entity to a new SQLAlchemy record.

    ``created_at`` is written explicitly rather than left to the column's
    ``server_default``. Without it the entity ``create_checkpoint`` returns
    would disagree with the row it just wrote, and the contract scenarios
    compare the two.

    Returns
    -------
    ReviewCheckpointRecord
        An unattached record ready for ``session.add``.
    """
    return ReviewCheckpointRecord(
        id=checkpoint.id,
        generation_run_id=checkpoint.generation_run_id,
        node=checkpoint.node,
        prompt=checkpoint.prompt,
        options=list(checkpoint.options),
        status=checkpoint.status,
        response_action=checkpoint.response_action,
        response_payload=dict(checkpoint.response_payload),
        resolved_at=checkpoint.responded_at,
        responded_by=checkpoint.responded_by,
        created_at=checkpoint.created_at,
    )


def resolved_values(checkpoint: Checkpoint) -> dict[str, object]:
    """Return the column values a resolved checkpoint implies.

    The compare-and-set ``UPDATE`` writes exactly these columns, so naming them
    once keeps the statement and the record the caller receives from drifting
    apart. Nothing else may write a resolved field.

    Returns
    -------
    dict of str to object
        Column names mapped to the values a resolution writes.
    """
    return {
        "status": checkpoint.status,
        "response_action": checkpoint.response_action,
        "response_payload": dict(checkpoint.response_payload),
        "resolved_at": checkpoint.responded_at,
        "responded_by": checkpoint.responded_by,
    }
