# Benchmark source locations are intentionally stable.
"""Dynamic and registered live symbols for false-positive controls."""

import typing as typ


class RegisteredFunction(typ.Protocol):  # noqa: D101
    __name__: str

    def __call__(self) -> int: ...  # noqa: D102


REGISTRY: dict[str, RegisteredFunction] = {}


def register(function: RegisteredFunction) -> RegisteredFunction:  # noqa: D103
    REGISTRY[function.__name__] = function
    return function


@register
def registered_plugin() -> int:  # noqa: D103
    return 29


class DynamicHandler:  # noqa: D101
    def invoked_by_name(self) -> int:  # noqa: D102, PLR6301
        return 31


class CallableHandler:  # noqa: D101
    def __call__(self) -> int:  # noqa: D102
        return 37


DYNAMIC_RESULT = getattr(DynamicHandler(), "invoked_by_name")()  # noqa: B009
REGISTERED_RESULT = REGISTRY["registered_plugin"]()
CALLABLE_RESULT = CallableHandler()()
