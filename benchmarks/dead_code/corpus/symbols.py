# Benchmark source locations are intentionally stable.
"""Ordinary live and unused Python symbols for detector comparison."""

import math  # noqa: F401
import statistics


def _unused_function() -> int:
    """Return a result from an intentionally unused function.

    Returns
    -------
    int
        Constant function result.
    """
    return 11


class _UnusedClass:
    """Represent an intentionally unused class fixture.

    Attributes
    ----------
    value : int
        Constant class value.
    """

    value = 13


def _used_function(value: int) -> float:
    """Calculate the mean of a value and a fixed comparison value.

    Parameters
    ----------
    value : int
        Value to include in the mean.

    Returns
    -------
    float
        Mean of ``value`` and one.
    """
    unused_local = 17  # noqa: F841
    return statistics.mean([value, 1])


def _function_with_unused_parameter(
    value: int,
    unused_parameter: int,
) -> int:
    """Double ``value`` while retaining an unused fixture parameter.

    Parameters
    ----------
    value : int
        Value to double.
    unused_parameter : int
        Unused parameter retained for dead-code detection coverage.

    Returns
    -------
    int
        Twice ``value``.
    """
    return value * 2


class UsedClass:
    """Provide a method used by the benchmark fixture."""

    def value(self) -> int:  # noqa: PLR6301 - instance call retains the instantiated-class fixture.
        """Return the class fixture's constant value.

        Returns
        -------
        int
            Constant instance value.
        """
        return 19


def exported_function() -> int:
    """Return the exported fixture function's constant value.

    Returns
    -------
    int
        Constant function result.
    """
    return 23


USED_RESULT = _used_function(3)
PARAMETER_RESULT = _function_with_unused_parameter(5, 7)
CLASS_RESULT = UsedClass().value()
