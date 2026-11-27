"""Redaction helpers shared by snapshots containing domain identifiers.

Use these helpers when a snapshot's structure is the contract but concrete
UUID values or content hashes are incidental test data. Keep semantic values
intact; do not use this module to hide secrets that should never reach the
test result.
"""

import re
import uuid

_UUID_PATTERN = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}"
    r"-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)

_SHA256_PATTERN = re.compile(r"\bsha256:[0-9a-fA-F]{64}\b")


def redact_snapshot_uuids(value: object) -> object:
    """Replace UUID values recursively while preserving snapshot structure.

    Parameters
    ----------
    value : object
        UUID, string, dictionary, list, or tuple to traverse recursively.
        Values of other types pass through unchanged.

    Returns
    -------
    object
        A structure with UUID objects and UUID substrings replaced.

    Raises
    ------
    ValueError
        If distinct dictionary keys collide after UUID redaction.

    Examples
    --------
    ``redact_snapshot_uuids({"id": UUID(int=0)})`` returns
    ``{"id": "<uuid>"}``.
    """
    match value:
        case uuid.UUID():
            return "<uuid>"
        case str():
            return _UUID_PATTERN.sub("<uuid>", value)
        case dict():
            redacted: dict[object, object] = {}
            for key, item in value.items():
                redacted_key = redact_snapshot_uuids(key)
                if redacted_key in redacted:
                    msg = "distinct dictionary keys collide after UUID redaction"
                    raise ValueError(msg)
                redacted[redacted_key] = redact_snapshot_uuids(item)
            return redacted
        case list():
            return [redact_snapshot_uuids(item) for item in value]
        case tuple():
            return tuple(redact_snapshot_uuids(item) for item in value)
        case _:
            return value


def redact_snapshot_hashes(value: object) -> object:
    """Replace SHA-256 content hashes recursively, preserving structure.

    Snapshots pin the presence of a content hash without reproducing the
    digest, which the ambrleaks gate treats as a potentially leaked runtime
    value. Semantic values of other types pass through unchanged.

    Parameters
    ----------
    value : object
        String, dictionary, list, or tuple to traverse recursively. Values of
        other types pass through unchanged.

    Returns
    -------
    object
        A structure whose ``sha256:`` digests are replaced with ``<sha256>``.
        UUID redaction is not applied here; compose it with
        :func:`redact_snapshot_uuids` when both are needed.

    Raises
    ------
    ValueError
        If distinct dictionary keys collide after hash redaction.

    Examples
    --------
    ``redact_snapshot_hashes({"content_hash": "sha256:" + "a" * 64})``
    returns ``{"content_hash": "<sha256>"}``.
    """
    match value:
        case str():
            return _SHA256_PATTERN.sub("<sha256>", value)
        case dict():
            redacted: dict[object, object] = {}
            for key, item in value.items():
                redacted_key = redact_snapshot_hashes(key)
                if redacted_key in redacted:
                    msg = "distinct dictionary keys collide after hash redaction"
                    raise ValueError(msg)
                redacted[redacted_key] = redact_snapshot_hashes(item)
            return redacted
        case list():
            return [redact_snapshot_hashes(item) for item in value]
        case tuple():
            return tuple(redact_snapshot_hashes(item) for item in value)
        case _:
            return value
