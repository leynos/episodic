"""Typed dependency contracts for the Falcon API adapter.

This module defines the explicit inbound-adapter dependency object used by the
Falcon app factory. The HTTP layer receives ports and readiness hooks through
this contract instead of importing concrete adapter implementations directly.
"""

import collections.abc as cabc
import dataclasses as dc
import inspect
import typing as typ

from .authorization import AuthorizationPort, PermitAll

if typ.TYPE_CHECKING:
    from episodic.canonical.object_store import ObjectStorePort
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


def _validate_readiness_probe(
    probe: object,
    *,
    label: str = "ApiDependencies.readiness_probes entries",
) -> None:
    """Require a readiness-probe entry to have a non-empty name and async check."""
    if not hasattr(probe, "name") or not isinstance(probe.name, str):  # type: ignore[union-attr]
        msg = f"{label} must define a string name."
        raise TypeError(msg)
    if not probe.name.strip():  # type: ignore[union-attr]
        msg = f"{label} must define a non-empty name."
        raise ValueError(msg)
    if not hasattr(probe, "check"):
        msg = f"{label} must define an async check."
        raise TypeError(msg)
    _validate_async_callable(probe.check, label)  # type: ignore[union-attr]


def _validate_authorization_port(port: object) -> None:
    """Require an authorization port with an async decision method."""
    if not isinstance(port, AuthorizationPort):
        msg = "ApiDependencies.authorization must implement AuthorizationPort."
        raise TypeError(msg)
    _validate_async_callable(port.decide, "ApiDependencies.authorization.decide")


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
    object_store: ObjectStorePort | None = None
    upload_max_bytes: int = 25 * 1024 * 1024
    upload_content_types: tuple[str, ...] = (
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "text/plain",
        "text/markdown",
        "text/html",
    )
    readiness_probes: tuple[ReadinessProbe, ...] = ()
    shutdown_hooks: tuple[ShutdownHook, ...] = ()
    llm_port: LLMPort | None = None
    authorization: AuthorizationPort = dc.field(default_factory=PermitAll)

    def __post_init__(self) -> None:
        """Validate the dependency contract."""
        if not callable(self.uow_factory):
            msg = "ApiDependencies.uow_factory must be callable."
            raise TypeError(msg)
        _validate_authorization_port(self.authorization)
        object.__setattr__(self, "readiness_probes", tuple(self.readiness_probes))
        object.__setattr__(self, "shutdown_hooks", tuple(self.shutdown_hooks))
        for probe in self.readiness_probes:
            _validate_readiness_probe(probe)
        for shutdown_hook in self.shutdown_hooks:
            _validate_async_callable(
                shutdown_hook,
                "ApiDependencies.shutdown_hooks entries",
            )
