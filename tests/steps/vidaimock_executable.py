"""Locate the Vidai Mock binary that the live behavioural fixtures run.

Resolution is kept apart from the launch harness because it is the one part of
startup that consults the environment rather than the child. It either finds
the binary or reports its absence in the way the caller's context requires,
and separating it leaves the harness free of `pytest`, which it would
otherwise need only to signal this one condition.
"""

import os
import shutil

import pytest


def resolve_vidaimock_executable() -> str:
    """Return the Vidai Mock executable path, or skip/fail as the environment asks.

    Returns
    -------
    str
        The absolute path of the Vidai Mock binary on `PATH`.

    Raises
    ------
    pytest.fail.Exception
        In CI, where a missing binary must fail the scenario rather than skip
        it and quietly reduce coverage.
    pytest.skip.Exception
        Locally, where a missing binary is a developer's choice, not a fault.
    AssertionError
        Never, in practice. Both calls above raise; this keeps every path an
        explicit return or raise.
    """  # ruff: ignore[docstring-extraneous-exception] - Both signals come from pytest.fail/pytest.skip below.
    path = shutil.which("vidaimock")
    if path is not None:
        return path
    reason = "vidaimock executable not found in PATH"
    if os.getenv("CI"):
        pytest.fail(reason)
    pytest.skip(reason)
    # Both calls above raise, so this is unreachable; it keeps every path in
    # this function an explicit return or raise for the reader and the linter.
    raise AssertionError(reason)  # pragma: no cover
