"""Shared, low-level validation primitives for benchmark report parsers.

Both benchmark suites normalize untrusted detector JSON before scoring. Keep
only schema and path validation here; detector-specific parsing and scoring
remain in their benchmark packages. Each helper returns a normalized value or
raises a precise exception at the report boundary, keeping later scoring code
free of repeated shape checks.
"""

import typing as typ
from collections import abc as cabc
from pathlib import Path


def mapping(value: object, *, context: str) -> cabc.Mapping[str, object]:
    """Validate and return a string-keyed JSON object.

    Parameters
    ----------
    value : object
        Candidate decoded JSON value.
    context : str
        Human-readable path used in validation messages.

    Returns
    -------
    collections.abc.Mapping[str, object]
        The validated object with string keys.

    Raises
    ------
    TypeError
        If ``value`` is not an object or has a non-string key.
    """
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
    """Validate and return a non-string JSON array.

    Parameters
    ----------
    value : object
        Candidate decoded JSON value.
    context : str
        Human-readable path used in validation messages.
    none_is_empty : bool, default=False
        Treat ``None`` as an empty sequence when a detector uses null for no
        results.

    Returns
    -------
    collections.abc.Sequence[object]
        The validated sequence, or an empty tuple for an allowed ``None``.

    Raises
    ------
    TypeError
        If the value is not a non-string sequence.
    """
    if value is None and none_is_empty:
        return ()
    if not isinstance(value, cabc.Sequence) or isinstance(value, (str, bytes)):
        msg = f"{context} must be a JSON array"
        raise TypeError(msg)
    return value


def string(value: object, *, context: str) -> str:
    """Validate and return a string report field.

    Parameters
    ----------
    value : object
        Candidate decoded JSON value.
    context : str
        Human-readable field path used in the error message.

    Returns
    -------
    str
        The validated string.

    Raises
    ------
    TypeError
        If ``value`` is not a string.
    """
    if not isinstance(value, str):
        msg = f"{context} must be a string"
        raise TypeError(msg)
    return value


def positive_line(value: object, *, context: str) -> int:
    """Validate and return a positive, non-boolean line number.

    Parameters
    ----------
    value : object
        Candidate decoded JSON value.
    context : str
        Human-readable field path used in the error message.

    Returns
    -------
    int
        A line number greater than or equal to one.

    Raises
    ------
    TypeError
        If ``value`` is not an integer or is a boolean.
    ValueError
        If the integer is less than one.
    """
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
    """Normalize a source path relative to the corpus root.

    Parameters
    ----------
    raw_path : object
        Candidate detector path, expected to be a string.
    corpus_root : pathlib.Path
        Root directory against which relative paths are resolved.
    subject : str
        Name of the report object used in validation messages.

    Returns
    -------
    str
        A normalized POSIX path relative to ``corpus_root``.

    Notes
    -----
    The :class:`TypeError` raised by :func:`string` is propagated when
    ``raw_path`` is not a string.

    Raises
    ------
    ValueError
        If the resolved path escapes ``corpus_root``.
    """
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
