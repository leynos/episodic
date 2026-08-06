# Benchmark source locations are intentionally stable.
"""Ordinary live and unused Python symbols for detector comparison."""

import math  # noqa: F401
import statistics


def _unused_function() -> int:
    return 11


class _UnusedClass:
    value = 13


def _used_function(value: int) -> float:
    unused_local = 17  # noqa: F841
    return statistics.mean([value, 1])


def _function_with_unused_parameter(
    value: int,
    unused_parameter: int,
) -> int:
    return value * 2


class UsedClass:  # noqa: D101
    def value(self) -> int:  # noqa: D102, PLR6301
        return 19


def exported_function() -> int:  # noqa: D103
    return 23


USED_RESULT = _used_function(3)
PARAMETER_RESULT = _function_with_unused_parameter(5, 7)
CLASS_RESULT = UsedClass().value()
