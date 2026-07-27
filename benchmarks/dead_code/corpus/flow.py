# ruff: noqa
"""Reachable and unreachable statements for control-flow comparison."""


def after_return() -> int:
    return 41
    unreachable_after_return = 43


def after_raise() -> None:
    raise RuntimeError("expected benchmark exception")
    unreachable_after_raise = 47


def after_continue(values: tuple[int, ...]) -> int:
    for value in values:
        continue
        unreachable_after_continue = value
    return len(values)


def after_break(values: tuple[int, ...]) -> int:
    for value in values:
        break
        unreachable_after_break = value
    return len(values)


def constant_false_branch() -> int:
    if False:
        unreachable_false_branch = 53
    return 59


def conditional_return(flag: bool) -> int:
    if flag:
        return 61
    reachable_after_conditional = 67
    return reachable_after_conditional


RETURN_RESULT = after_return()
try:
    after_raise()
except RuntimeError:
    pass
CONTINUE_RESULT = after_continue((1, 2))
BREAK_RESULT = after_break((3, 4))
FALSE_RESULT = constant_false_branch()
CONDITIONAL_RESULT = conditional_return(False)
