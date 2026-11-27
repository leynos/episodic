"""Typed dependency contracts for the Falcon API adapter.

This module defines the explicit inbound-adapter dependency object used by the
Falcon app factory. The HTTP layer receives ports and readiness hooks through
this contract instead of importing concrete adapter implementations directly.
"""

import collections.abc as cabc
import dataclasses as dc
import typing as typ

from episodic.canonical.generation_quality import QualityMode
from episodic.canonical.validation import (
    validate_async_callable,
    validate_sync_callable,
)
from episodic.observability import NoopMetrics, NoopTracer, PerfCounterClock

from .authorization import AuthorizationPort, PermitAll

if typ.TYPE_CHECKING:
    from episodic.canonical.health import HealthObserver
    from episodic.canonical.object_store import ObjectStorePort
    from episodic.generation import GenerationRunLauncher, GenerationSourceLimits
    from episodic.llm import LLMPort
    from episodic.observability import MetricsPort, MonotonicClockPort, TracerPort

    from .types import UowFactory

type ReadinessCheck = cabc.Callable[[], cabc.Coroutine[None, None, bool]]
type ShutdownHook = cabc.Callable[[], cabc.Coroutine[None, None, None]]


class UnmappedErrorEmitter(typ.Protocol):
    """Narrow logging port used by the unmapped-error HTTP boundary."""

    def __call__(
        self,
        template: str,
        /,
        *args: object,
        exc_info: object | None = None,
    ) -> None:
        """Emit one already-sanitized unmapped API error record."""


def _validate_readiness_probe(
    probe: object,
    *,
    label: str = "ApiDependencies.readiness_probes entries",
) -> None:
    """Require a readiness-probe entry to have a non-empty name and async check."""
    name = getattr(probe, "name", None)
    if not isinstance(name, str):
        msg = f"{label} must define a string name."
        raise TypeError(msg)
    if not name.strip():
        msg = f"{label} must define a non-empty name."
        raise ValueError(msg)
    validate_async_callable(getattr(probe, "check", None), f"{label} check")


def _validate_authorization_port(port: object) -> None:
    """Require an authorization port with an async decision method."""
    if not isinstance(port, AuthorizationPort):
        msg = "ApiDependencies.authorization must implement AuthorizationPort."
        raise TypeError(msg)
    validate_async_callable(port.decide, "ApiDependencies.authorization.decide")


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
        validate_async_callable(self.check, "ReadinessProbe.check")


def _validate_accepted_quality_modes(dependencies: ApiDependencies) -> None:
    """Normalize and validate the accepted quality-mode capability set."""
    modes = frozenset(dependencies.accepted_quality_modes)
    object.__setattr__(dependencies, "accepted_quality_modes", modes)
    if QualityMode.DRAFT_WITHOUT_QA not in modes:
        msg = "ApiDependencies.accepted_quality_modes must include draft_without_qa."
        raise ValueError(msg)


def _validate_health_observer(observer: object) -> None:
    """Require a supplied health observer to expose ``observe``."""
    if observer is not None and not hasattr(observer, "observe"):
        msg = "ApiDependencies.health_observer must define observe()."
        raise TypeError(msg)


def _normalize_and_validate_hooks(dependencies: ApiDependencies) -> None:
    """Freeze the hook tuples and validate each entry."""
    object.__setattr__(
        dependencies, "readiness_probes", tuple(dependencies.readiness_probes)
    )
    object.__setattr__(
        dependencies, "shutdown_hooks", tuple(dependencies.shutdown_hooks)
    )
    for probe in dependencies.readiness_probes:
        _validate_readiness_probe(probe)
    for shutdown_hook in dependencies.shutdown_hooks:
        validate_async_callable(
            shutdown_hook,
            "ApiDependencies.shutdown_hooks entries",
        )


@dc.dataclass(frozen=True, slots=True)
class ApiDependencies:
    """Group the ports and probes required by the Falcon API adapter.

    Parameters
    ----------
    uow_factory : UowFactory
        Factory used to create canonical units of work.
    unmapped_error_emitter : UnmappedErrorEmitter | None
        Optional logger callback injected into the Falcon error serializer.
        When omitted, :func:`create_app` binds the production logging port at
        application construction time.
    """

    uow_factory: UowFactory
    object_store: ObjectStorePort | None = None
    upload_max_bytes: int = 50 * 1024 * 1024
    upload_content_types: tuple[str, ...] = (
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "text/plain",
        "text/markdown",
        "text/html",
    )
    readiness_probes: tuple[ReadinessProbe, ...] = ()
    health_observer: HealthObserver | None = None
    shutdown_hooks: tuple[ShutdownHook, ...] = ()
    llm_port: LLMPort | None = None
    launcher: GenerationRunLauncher | None = None
    generation_source_limits: GenerationSourceLimits | None = None
    metrics: MetricsPort = dc.field(default_factory=NoopMetrics)
    monotonic_clock: MonotonicClockPort = dc.field(default_factory=PerfCounterClock)
    tracer: TracerPort = dc.field(default_factory=NoopTracer)
    authorization: AuthorizationPort = dc.field(default_factory=PermitAll)
    accepted_quality_modes: frozenset[QualityMode] = frozenset({
        QualityMode.DRAFT_WITHOUT_QA
    })
    unmapped_error_emitter: UnmappedErrorEmitter | None = None

    def __post_init__(self) -> None:
        """Validate the dependency contract."""
        if not callable(self.uow_factory):
            msg = "ApiDependencies.uow_factory must be callable."
            raise TypeError(msg)
        validate_sync_callable(
            self.unmapped_error_emitter,
            "ApiDependencies.unmapped_error_emitter",
            allow_none=True,
        )
        _validate_authorization_port(self.authorization)
        _validate_accepted_quality_modes(self)
        _validate_health_observer(self.health_observer)
        _normalize_and_validate_hooks(self)

    def readiness_observer(self) -> HealthObserver:
        """Return the domain health observer used by the readiness resource."""
        from episodic.canonical.health import ProbeHealthObserver

        if self.health_observer is not None:
            return self.health_observer
        return ProbeHealthObserver.from_checks(
            (probe.name, probe.check) for probe in self.readiness_probes
        )
