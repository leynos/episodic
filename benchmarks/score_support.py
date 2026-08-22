"""Shared, low-level validation primitives for benchmark report parsers.

Both benchmark suites normalize untrusted detector JSON before scoring. Keep
only schema and path validation here; detector-specific parsing and scoring
remain in their benchmark packages.
"""

import typing as typ
from collections import abc as cabc
from pathlib import Path


def mapping(value: object, *, context: str) -> cabc.Mapping[str, object]:
    """Validate and return a string-keyed mapping."""
    if not isinstance(value, cabc.Mapping):
        msg = f"{context} must be a JSON object"
        raise TypeError(msg)
    if not all(isinstance(key, str) for key in value):
        msg = f"{context} keys must be strings"
        raise TypeError(msg)
    return typ.cast("cabc.Mapping[str, object]", value)


def sequence(
    value: object,
    *,
    context: str,
    none_is_empty: bool = False,
) -> cabc.Sequence[object]:
    """Validate and return a non-string JSON array."""
    if value is None and none_is_empty:
        return ()
    if not isinstance(value, cabc.Sequence) or isinstance(value, (str, bytes)):
        msg = f"{context} must be a JSON array"
        raise TypeError(msg)
    return value


def string(value: object, *, context: str) -> str:
    """Validate and return a string value."""
    if not isinstance(value, str):
        msg = f"{context} must be a string"
        raise TypeError(msg)
    return value


def positive_line(value: object, *, context: str) -> int:
    """Validate and return a positive, non-boolean line number."""
    if not isinstance(value, int) or isinstance(value, bool):
        msg = f"{context} must be a positive integer"
        raise TypeError(msg)
    if value < 1:
        msg = f"{context} must be positive"
        raise ValueError(msg)
    return value


def relative_source_path(
    raw_path: object,
    corpus_root: Path,
    *,
    subject: str,
) -> str:
    """Normalize a validated source path relative to the corpus root."""
    root = corpus_root.resolve()
    path = Path(string(raw_path, context=f"{subject} path"))
    if not path.is_absolute():
        path = root / path
    path = path.resolve()
    try:
        return path.relative_to(root).as_posix()
    except ValueError as error:
        msg = f"{subject} path {path} is outside corpus root {root}"
        raise ValueError(msg) from error
