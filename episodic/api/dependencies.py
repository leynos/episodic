"""Typed dependency contracts for the Falcon API adapter.

This module defines the explicit inbound-adapter dependency object used by the
Falcon app factory. The HTTP layer receives ports and readiness hooks through
this contract instead of importing concrete adapter implementations directly.
"""

from __future__ import annotations

import collections.abc as cabc
import dataclasses as dc
import typing as typ

if typ.TYPE_CHECKING:
    from episodic.llm import LLMPort

    from .types import UowFactory

type ReadinessCheck = cabc.Callable[[], cabc.Awaitable[bool]]


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
        if not callable(self.check):
            msg = "ReadinessProbe.check must be callable."
            raise TypeError(msg)


@dc.dataclass(frozen=True, slots=True)
class ApiDependencies:
    """Group the ports and probes required by the Falcon API adapter."""

    uow_factory: UowFactory
    readiness_probes: tuple[ReadinessProbe, ...] = ()
    llm_port: LLMPort | None = None

    def __post_init__(self) -> None:
        """Validate the dependency contract."""
        if not callable(self.uow_factory):
            msg = "ApiDependencies.uow_factory must be callable."
            raise TypeError(msg)
        object.__setattr__(self, "readiness_probes", tuple(self.readiness_probes))
