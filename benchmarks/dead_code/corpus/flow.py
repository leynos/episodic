# Benchmark source locations are intentionally stable.
"""Reachable and unreachable statements for control-flow comparison."""

EXPECTED_BENCHMARK_EXCEPTION_MESSAGE = "expected benchmark exception"


def after_return() -> int:  # noqa: RET503
    """Return the fixed benchmark value.

    Returns
    -------
    int
        The fixed benchmark value.
    """
    return 41
    unreachable_after_return = 43  # noqa: F841


def after_raise() -> None:
    """Raise the expected benchmark exception.

    Raises
    ------
    ValueError
        Always, as required to exercise the unreachable assignment.
    """
    raise ValueError(EXPECTED_BENCHMARK_EXCEPTION_MESSAGE)
    unreachable_after_raise = 47  # noqa: F841


def after_continue(values: tuple[int, ...]) -> int:
    """Return the number of values after skipping each loop body.

    Parameters
    ----------
    values : tuple[int, ...]
        Values iterated only to exercise an unreachable assignment.

    Returns
    -------
    int
        The number of supplied values.
    """
    for value in values:
        continue
        unreachable_after_continue = value  # noqa: F841
    return len(values)


def after_break(values: tuple[int, ...]) -> int:
    """Return the number of values after breaking the loop.

    Parameters
    ----------
    values : tuple[int, ...]
        Values iterated only to exercise an unreachable assignment.

    Returns
    -------
    int
        The number of supplied values.
    """
    for value in values:
        break
        unreachable_after_break = value  # noqa: F841
    return len(values)


def constant_false_branch() -> int:
    """Return the fixed value after an unreachable branch.

    Returns
    -------
    int
        The fixed benchmark value.
    """
    if False:
        unreachable_false_branch = 53  # noqa: F841
    return 59


def conditional_return(flag: bool) -> int:  # noqa: FBT001
    """Return the fixed value after the conditional branch.

    Parameters
    ----------
    flag : bool
        Whether to take the early return branch.

    Returns
    -------
    int
        The fixed benchmark value.
    """
    if flag:
        return 61
    reachable_after_conditional = 67
    return reachable_after_conditional  # noqa: RET504


RETURN_RESULT = after_return()
try:  # noqa: SIM105
    after_raise()
except ValueError:
    pass
CONTINUE_RESULT = after_continue((1, 2))
BREAK_RESULT = after_break((3, 4))
FALSE_RESULT = constant_false_branch()
CONDITIONAL_RESULT = conditional_return(False)  # noqa: FBT003
