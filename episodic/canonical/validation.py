"""Transport-free runtime validation helpers shared across layers.

This module owns small argument-shape validators that both the domain layer
and inbound adapters need at object-construction time. It belongs to the
hexagonal architecture domain layer, so adapters may import it while it
imports nothing beyond the standard library.

Scope and re-use policy: helpers here must be dependency-free, side-effect
free, and applicable to any layer. Domain-specific validation stays with the
domain type it guards. `validate_callable` checks the general callback shape;
`validate_sync_callable` and `validate_async_callable` enforce execution mode
when an adapter's contract requires it.
"""

import inspect
import typing as typ

if typ.TYPE_CHECKING:
    import collections.abc as cabc


def validate_callable(
    callback: object,
    attribute_name: str,
    *,
    allow_none: bool = False,
) -> None:
    """Require a callable dependency, optionally allowing a missing callback.

    Parameters
    ----------
    callback : object
        Candidate callback supplied by configuration or dependency wiring.
    attribute_name : str
        Human-readable attribute label used in error messages.
    allow_none : bool, default=False
        Whether ``None`` represents an intentionally absent optional callback.

    Raises
    ------
    TypeError
        If ``callback`` is not callable and is not an allowed ``None`` value.

    Examples
    --------
    >>> validate_callable(str, "Serializer.encode")
    >>> validate_callable(None, "OptionalEmitter", allow_none=True)
    """
    if callback is None and allow_none:
        return
    if not callable(callback):
        msg = f"{attribute_name} must be callable."
        raise TypeError(msg)


def validate_async_callable(callback: object, attribute_name: str) -> None:
    """Require a coroutine function or an object with an async ``__call__``.

    Parameters
    ----------
    callback : object
        Candidate callback supplied by configuration or dependency wiring.
    attribute_name : str
        Human-readable attribute label used in error messages.

    Raises
    ------
    TypeError
        If the callback is not callable or is not declared async.

    Examples
    --------
    >>> async def probe() -> bool:
    ...     return True
    >>> validate_async_callable(probe, "ReadinessProbe.check")
    """
    validate_callable(callback, attribute_name)

    if inspect.iscoroutinefunction(callback) or inspect.iscoroutinefunction(
        type(callback).__call__
    ):
        return

    msg = f"{attribute_name} must be an async callable returning an awaitable."
    raise TypeError(msg)


def validate_sync_callable(
    callback: object,
    attribute_name: str,
    *,
    allow_none: bool = False,
) -> None:
    """Require a callable dependency that does not create an awaitable.

    Parameters
    ----------
    callback : object
        Candidate callback supplied by configuration or dependency wiring.
    attribute_name : str
        Human-readable attribute label used in error messages.
    allow_none : bool, default=False
        Whether ``None`` represents an intentionally absent optional callback.

    Raises
    ------
    TypeError
        If ``callback`` is not callable or is declared as a coroutine function.

    Examples
    --------
    >>> validate_sync_callable(str, "Serializer.encode")
    >>> validate_sync_callable(None, "OptionalEmitter", allow_none=True)
    """
    if callback is None and allow_none:
        return
    validate_callable(callback, attribute_name)

    call_method = typ.cast("cabc.Callable[..., object]", callback).__call__
    if inspect.iscoroutinefunction(callback) or inspect.iscoroutinefunction(
        call_method
    ):
        msg = f"{attribute_name} must be a synchronous callable."
        raise TypeError(msg)
