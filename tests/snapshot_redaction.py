"""Redaction helpers shared by snapshots containing domain identifiers.

Use these helpers when a snapshot's structure is the contract but concrete
UUID values are incidental test data. Keep semantic values intact; do not use
this module to hide secrets that should never reach the test result.
"""

import re
import uuid

_UUID_PATTERN = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}"
    r"-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)


def redact_snapshot_uuids(value: object) -> object:
    """Replace UUID values recursively while preserving snapshot structure.

    Examples
    --------
    ``redact_snapshot_uuids({"id": UUID(int=0)})`` returns
    ``{"id": "<uuid>"}``.

    Returns
    -------
    object
        A structure with UUID objects and UUID substrings replaced.
    """
    match value:
        case uuid.UUID():
            return "<uuid>"
        case str():
            return _UUID_PATTERN.sub("<uuid>", value)
        case dict():
            return {key: redact_snapshot_uuids(item) for key, item in value.items()}
        case list():
            return [redact_snapshot_uuids(item) for item in value]
        case tuple():
            return tuple(redact_snapshot_uuids(item) for item in value)
        case _:
            return value
