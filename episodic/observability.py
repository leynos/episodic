"""Shared observability ports for bounded metrics and monotonic timing.

This module defines the canonical observability ports that adapters and
services across the codebase wire against:

- :class:`MetricsPort` is the canonical metrics interface for new code. Its
  label parameters are typed as ``collections.abc.Mapping[str, str]`` so
  callers can pass either ``dict`` or read-only mapping values, which keeps
  the port aligned with structural typing best practice for input parameters.
- :class:`MonotonicClockPort` is the canonical clock port for measuring
  elapsed operation time. Feature modules (for example
  :mod:`episodic.qa.chrono`) reuse this port directly rather than declaring
  parallel hierarchies.

:class:`episodic.metrics_ports.BoundedMetricsPort` is a deliberately narrower
structural subtype with ``dict[str, str]`` labels, retained because feature-
specific ports (such as :class:`episodic.qa.chrono.ChronoMetricsPort`)
historically extend it. Any adapter that satisfies :class:`MetricsPort` also
satisfies :class:`BoundedMetricsPort` for callers that build their label
dicts as concrete ``dict`` instances.
"""

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
