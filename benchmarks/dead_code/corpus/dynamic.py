# Benchmark source locations are intentionally stable.
"""Dynamic and registered live symbols for false-positive controls."""

import typing as typ


class RegisteredFunction(typ.Protocol):
    """Describe a zero-argument callable that can enter the registry.

    Attributes
    ----------
    __name__ : str
        Name used as the registry key.
    """

    __name__: str

    def __call__(self) -> int:
        """Invoke the registered callable.

        Returns
        -------
        int
            Result produced by the callable.
        """
        ...


REGISTRY: dict[str, RegisteredFunction] = {}


def register(function: RegisteredFunction) -> RegisteredFunction:
    """Store a callable under its declared name.

    Parameters
    ----------
    function : RegisteredFunction
        Callable to add to the registry.

    Returns
    -------
    RegisteredFunction
        The same callable passed in ``function``.
    """
    REGISTRY[function.__name__] = function
    return function


@register
def registered_plugin() -> int:
    """Return the result exposed by the registered plugin.

    Returns
    -------
    int
        Constant plugin result.
    """
    return 29


class DynamicHandler:
    """Provide a method resolved through dynamic attribute lookup."""

    def invoked_by_name(self) -> int:  # noqa: PLR6301 - dynamic getattr requires an instance method.
        """Return the result of the dynamically selected method.

        Returns
        -------
        int
            Constant handler result.
        """
        return 31


class CallableHandler:
    """Provide a callable object for invocation-based discovery."""

    def __call__(self) -> int:
        """Return the result produced when the handler is called.

        Returns
        -------
        int
            Constant handler result.
        """
        return 37


DYNAMIC_RESULT = getattr(DynamicHandler(), "invoked_by_name")()  # noqa: B009
REGISTERED_RESULT = REGISTRY["registered_plugin"]()
CALLABLE_RESULT = CallableHandler()()
