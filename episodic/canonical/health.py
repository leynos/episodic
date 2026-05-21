"""Transport-free health observation contracts.

This module defines the canonical health vocabulary used inside Episodic:
`HealthStatus`, `HealthCheck`, `HealthReport`, and the `HealthObserver` port.
Those types describe whether named service checks are healthy without
mentioning HTTP status codes, Falcon response objects, Kubernetes probe
settings, or any other transport concern.

Adapters can construct a `ProbeHealthObserver` with
`ProbeHealthObserver.from_checks({"database": check_database})`, where each
check is an async callable returning `True` for healthy and `False` for
unhealthy. Calling `await observer.observe()` returns a `HealthReport` that the
inbound adapter can translate into its own wire format.

The module belongs to the hexagonal architecture domain/port layer. It owns
health semantics, while HTTP, container, and Kubernetes adapters remain
responsible for adapting those semantics to their own protocols.
"""

import collections.abc as cabc
import dataclasses as dc
import enum
import inspect
import typing as typ

type HealthCheckCallback = cabc.Callable[[], cabc.Coroutine[None, None, bool]]


class HealthStatus(enum.StrEnum):
    """Canonical health states used before transport adaptation."""

    OK = "ok"
    ERROR = "error"


@dc.dataclass(frozen=True, slots=True)
class HealthCheck:
    """One named health observation."""

    name: str
    status: HealthStatus

    def __post_init__(self) -> None:
        """Validate the domain health-check contract."""
        if not self.name.strip():
            msg = "HealthCheck.name must be a non-empty string."
            raise ValueError(msg)


@dc.dataclass(frozen=True, slots=True)
class HealthReport:
    """Aggregated health observations."""

    status: HealthStatus
    checks: tuple[HealthCheck, ...]

    @classmethod
    def from_checks(cls, checks: cabc.Iterable[HealthCheck]) -> typ.Self:
        """Build a report that is healthy only when every check is healthy."""
        check_tuple = tuple(checks)
        status = (
            HealthStatus.OK
            if all(check.status is HealthStatus.OK for check in check_tuple)
            else HealthStatus.ERROR
        )
        return cls(status=status, checks=check_tuple)


class HealthObserver(typ.Protocol):
    """Port for observing service health without transport details."""

    async def observe(self) -> HealthReport:
        """Return the current health report."""


def _validate_async_callable(callback: object, attribute_name: str) -> None:
    """Require a coroutine function for health checks invoked with ``await``."""
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
class ProbeHealthObserver:
    """Observe health by evaluating named asynchronous checks."""

    _checks: tuple[tuple[str, HealthCheckCallback], ...] = ()

    @classmethod
    def from_checks(
        cls,
        checks: cabc.Mapping[str, HealthCheckCallback]
        | cabc.Iterable[tuple[str, HealthCheckCallback]],
    ) -> typ.Self:
        """Create an observer from named check callbacks."""
        check_tuple = typ.cast(
            "tuple[tuple[str, HealthCheckCallback], ...]",
            tuple(checks.items())
            if isinstance(checks, cabc.Mapping)
            else tuple(checks),
        )
        for name, callback in check_tuple:
            if not name.strip():
                msg = "Health check names must be non-empty strings."
                raise ValueError(msg)
            _validate_async_callable(callback, f"Health check {name!r}")
        return cls(_checks=check_tuple)

    async def observe(self) -> HealthReport:
        """Return failed observations when checks return false or raise."""
        checks: list[HealthCheck] = []
        for name, callback in self._checks:
            checks.append(
                HealthCheck(name=name, status=await self._observe_one(callback))
            )
        return HealthReport.from_checks(checks)

    @staticmethod
    async def _observe_one(callback: HealthCheckCallback) -> HealthStatus:
        """Treat unexpected check exceptions as a failed observation."""
        try:
            result = await callback()
        except Exception:  # noqa: BLE001 - health probes degrade to not-ready
            return HealthStatus.ERROR
        return HealthStatus.OK if result else HealthStatus.ERROR
