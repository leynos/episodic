"""Shared observability ports for bounded metrics and monotonic timing."""

from __future__ import annotations

import dataclasses as dc
import time
import typing as typ

if typ.TYPE_CHECKING:
    from collections import abc as cabc


class MetricsPort(typ.Protocol):
    """Bounded-cardinality metrics sink shared by adapters and services."""

    def increment_counter(
        self,
        name: str,
        *,
        labels: cabc.Mapping[str, str],
    ) -> None:
        """Increment a bounded-cardinality counter."""

    def observe_latency_ms(
        self,
        name: str,
        value: float,
        *,
        labels: cabc.Mapping[str, str],
    ) -> None:
        """Observe a latency measurement in milliseconds."""


class MonotonicClockPort(typ.Protocol):
    """Clock port for measuring elapsed operation time."""

    def monotonic_seconds(self) -> float:
        """Return a monotonic timestamp in seconds."""


@dc.dataclass(frozen=True, slots=True)
class NoopMetrics:
    """Default metrics sink used when no backend is wired."""

    def increment_counter(
        self,
        name: str,
        *,
        labels: cabc.Mapping[str, str],
    ) -> None:
        """Ignore counter increments."""

    def observe_latency_ms(
        self,
        name: str,
        value: float,
        *,
        labels: cabc.Mapping[str, str],
    ) -> None:
        """Ignore latency observations."""


@dc.dataclass(frozen=True, slots=True)
class PerfCounterClock:
    """Monotonic clock backed by Python's perf counter."""

    read_seconds: cabc.Callable[[], float] = time.perf_counter

    def monotonic_seconds(self) -> float:
        """Return the current monotonic timestamp in seconds."""
        return self.read_seconds()
