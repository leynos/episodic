"""Transport-free runtime validation helpers shared across layers.

This module owns small argument-shape validators that both the domain layer
and inbound adapters need at object-construction time. It belongs to the
hexagonal architecture domain layer, so adapters may import it while it
imports nothing beyond the standard library.

Scope and re-use policy: helpers here must be dependency-free, side-effect
free, and applicable to any layer. Domain-specific validation stays with the
domain type it guards.
"""

import inspect


def validate_async_callable(callback: object, attribute_name: str) -> None:
    """Require a coroutine function for callbacks invoked with ``await``.

    Parameters
    ----------
    callback : object
        Candidate callback supplied by configuration or dependency wiring.
    attribute_name : str
        Human-readable attribute label used in error messages.

    Raises
    ------
    TypeError
        If the callback is not callable or would not return an awaitable.

    Examples
    --------
    >>> async def probe() -> bool:
    ...     return True
    >>> validate_async_callable(probe, "ReadinessProbe.check")
    """
    if not callable(callback):
        msg = f"{attribute_name} must be callable."
        raise TypeError(msg)

    if inspect.iscoroutinefunction(callback) or inspect.iscoroutinefunction(
        type(callback).__call__
    ):
        return

    msg = f"{attribute_name} must be an async callable returning an awaitable."
    raise TypeError(msg)
