"""Shared bounded-cardinality metrics ports for operational adapters.

These protocols centralise counter, latency, and scalar observation contracts
so feature-specific ports such as ``ChronoMetricsPort`` and
``CpuTaskExecutorMetricsPort`` reuse one implementation strategy instead of
duplicating identical method signatures.

:class:`BoundedMetricsPort` is a narrower structural subtype of
:class:`episodic.observability.MetricsPort` whose label parameters are typed
as ``dict[str, str]`` rather than ``collections.abc.Mapping[str, str]``. New
code should prefer :class:`episodic.observability.MetricsPort`; the protocols
in this module are retained for the feature-specific ports that historically
extended :class:`BoundedMetricsPort` and for adapters that build their label
mappings as concrete ``dict`` instances.
"""

import dataclasses as dc
import typing as typ


class BoundedMetricsPort(typ.Protocol):
    """Bounded-cardinality metrics sink for counters and latency observations."""

    def increment_counter(
        self,
        name: str,
        *,
        labels: dict[str, str],
    ) -> None:
        """Increment a bounded-cardinality counter."""

    def observe_latency_ms(
        self,
        name: str,
        value: float,
        *,
        labels: dict[str, str],
    ) -> None:
        """Observe a latency measurement in milliseconds."""


class BoundedValueMetricsPort(BoundedMetricsPort, typ.Protocol):
    """Bounded-cardinality metrics sink that also records scalar values."""

    def observe_value(
        self,
        name: str,
        value: float,
        *,
        labels: dict[str, str],
    ) -> None:
        """Observe a non-latency numeric measurement."""


@dc.dataclass(frozen=True, slots=True)
class NoopBoundedMetrics:
    """Default metrics sink used when no backend is wired."""

    def increment_counter(
        self,
        name: str,
        *,
        labels: dict[str, str],
    ) -> None:
        """Ignore counter increments."""

    def observe_latency_ms(
        self,
        name: str,
        value: float,
        *,
        labels: dict[str, str],
    ) -> None:
        """Ignore latency observations."""


@dc.dataclass(frozen=True, slots=True)
class NoopBoundedValueMetrics(NoopBoundedMetrics):
    """Default value-metrics sink used when no backend is wired."""

    def observe_value(
        self,
        name: str,
        value: float,
        *,
        labels: dict[str, str],
    ) -> None:
        """Ignore non-latency observations."""


__all__ = [
    "BoundedMetricsPort",
    "BoundedValueMetricsPort",
    "NoopBoundedMetrics",
    "NoopBoundedValueMetrics",
]
