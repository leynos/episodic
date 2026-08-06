# Benchmark source locations are intentionally stable.
"""Reachable and unreachable statements for control-flow comparison."""


def after_return() -> int:  # noqa: D103, RET503
    return 41
    unreachable_after_return = 43  # noqa: F841


def after_raise() -> None:  # noqa: D103
    raise ValueError("expected benchmark exception")  # noqa: TRY003
    unreachable_after_raise = 47  # noqa: F841


def after_continue(values: tuple[int, ...]) -> int:  # noqa: D103
    for value in values:
        continue
        unreachable_after_continue = value  # noqa: F841
    return len(values)


def after_break(values: tuple[int, ...]) -> int:  # noqa: D103
    for value in values:
        break
        unreachable_after_break = value  # noqa: F841
    return len(values)


def constant_false_branch() -> int:  # noqa: D103
    if False:
        unreachable_false_branch = 53  # noqa: F841
    return 59


def conditional_return(flag: bool) -> int:  # noqa: D103, FBT001
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
