"""Canonical JSON encoding shared across bounded contexts.

Several services fingerprint or content-address structured payloads. They must
agree byte for byte, so the encoder lives in a leaf module rather than in any
one bounded context.

The encoding is determined enough for hashing when the payload contains only
strings, integers within the JSON-exact integer range, ``None``, arrays, and
nested mappings with string keys.
"""

import json
import typing as typ

if typ.TYPE_CHECKING:
    import collections.abc as cabc


def canonical_json_bytes(payload: cabc.Mapping[str, object]) -> bytes:
    """Return canonical UTF-8 JSON bytes for request fingerprinting.

    Parameters
    ----------
    payload : collections.abc.Mapping[str, object]
        JSON-compatible mapping to encode. Keys are sorted, separators are
        compact, and non-ASCII text is preserved as UTF-8.

    Returns
    -------
    bytes
        The canonical UTF-8 encoding of ``payload``.

    Examples
    --------
    >>> canonical_json_bytes({"b": 2, "a": 1})
    b'{"a":1,"b":2}'
    """
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
