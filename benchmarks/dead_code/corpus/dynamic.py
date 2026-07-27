# ruff: noqa
"""Dynamic and registered live symbols for false-positive controls."""

import typing as typ


class RegisteredFunction(typ.Protocol):
    __name__: str

    def __call__(self) -> int: ...


REGISTRY: dict[str, RegisteredFunction] = {}


def register(function: RegisteredFunction) -> RegisteredFunction:
    REGISTRY[function.__name__] = function
    return function


@register
def registered_plugin() -> int:
    return 29


class DynamicHandler:
    def invoked_by_name(self) -> int:
        return 31


class CallableHandler:
    def __call__(self) -> int:
        return 37


DYNAMIC_RESULT = getattr(DynamicHandler(), "invoked_by_name")()
REGISTERED_RESULT = REGISTRY["registered_plugin"]()
CALLABLE_RESULT = CallableHandler()()
