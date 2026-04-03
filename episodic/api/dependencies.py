"""Typed dependency contracts for the Falcon API adapter.

This module defines the explicit inbound-adapter dependency object used by the
Falcon app factory. The HTTP layer receives ports and readiness hooks through
this contract instead of importing concrete adapter implementations directly.
"""

import collections.abc as cabc
import dataclasses as dc
import inspect
import typing as typ

if typ.TYPE_CHECKING:
    from episodic.llm import LLMPort

    from .types import UowFactory

type ReadinessCheck = cabc.Callable[[], cabc.Coroutine[None, None, bool]]
type ShutdownHook = cabc.Callable[[], cabc.Coroutine[None, None, None]]


def _validate_async_callable(callback: object, attribute_name: str) -> None:
    """Require a coroutine function for adapter hooks invoked with ``await``."""
    if not callable(callback):
        msg = f"{attribute_name} must be callable."
        raise TypeError(msg)

    if inspect.iscoroutinefunction(callback) or inspect.iscoroutinefunction(
        type(callback).__call__
    ):
        return

    msg = f"{attribute_name} must be an async callable returning an awaitable."
    raise TypeError(msg)


@dc.dataclass(frozen=True, slots=True)
class ReadinessProbe:
    """Describe one infrastructural readiness check."""

    name: str
    check: ReadinessCheck

    def __post_init__(self) -> None:
        """Validate the probe contract at construction time."""
        if not self.name.strip():
            msg = "ReadinessProbe.name must be a non-empty string."
            raise ValueError(msg)
        _validate_async_callable(self.check, "ReadinessProbe.check")


@dc.dataclass(frozen=True, slots=True)
class ApiDependencies:
    """Group the ports and probes required by the Falcon API adapter."""

    uow_factory: UowFactory
    readiness_probes: tuple[ReadinessProbe, ...] = ()
    shutdown_hooks: tuple[ShutdownHook, ...] = ()
    llm_port: LLMPort | None = None

    def __post_init__(self) -> None:
        """Validate the dependency contract."""
        if not callable(self.uow_factory):
            msg = "ApiDependencies.uow_factory must be callable."
            raise TypeError(msg)
        object.__setattr__(self, "readiness_probes", tuple(self.readiness_probes))
        object.__setattr__(self, "shutdown_hooks", tuple(self.shutdown_hooks))
        for probe in self.readiness_probes:
            if not hasattr(probe, "name") or not isinstance(probe.name, str):
                msg = (
                    "ApiDependencies.readiness_probes entries must define "
                    "a string name."
                )
                raise TypeError(msg)
            if not probe.name.strip():
                msg = (
                    "ApiDependencies.readiness_probes entries must define "
                    "a non-empty name."
                )
                raise ValueError(msg)
            if not hasattr(probe, "check"):
                msg = (
                    "ApiDependencies.readiness_probes entries must define "
                    "an async check."
                )
                raise TypeError(msg)
            _validate_async_callable(
                probe.check,
                "ApiDependencies.readiness_probes entries",
            )
        for shutdown_hook in self.shutdown_hooks:
            _validate_async_callable(
                shutdown_hook,
                "ApiDependencies.shutdown_hooks entries",
            )
