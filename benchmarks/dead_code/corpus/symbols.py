# ruff: noqa
"""Ordinary live and unused Python symbols for detector comparison."""

import math
import statistics


def _unused_function() -> int:
    return 11


class _UnusedClass:
    value = 13


def _used_function(value: int) -> float:
    unused_local = 17
    return statistics.mean([value, 1])


def _function_with_unused_parameter(
    value: int,
    unused_parameter: int,
) -> int:
    return value * 2


class UsedClass:
    def value(self) -> int:
        return 19


def exported_function() -> int:
    return 23


USED_RESULT = _used_function(3)
PARAMETER_RESULT = _function_with_unused_parameter(5, 7)
CLASS_RESULT = UsedClass().value()
