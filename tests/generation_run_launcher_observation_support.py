"""Metrics-observation doubles shared by generation-run launcher tests."""

import dataclasses as dc
import typing as typ

if typ.TYPE_CHECKING:
    import collections.abc as cabc


@dc.dataclass(frozen=True, slots=True)
class MetricObservation:
    """One metrics call captured by :class:`RecordingMetrics`.

    Attributes
    ----------
    kind : str
        Metrics method that ran: ``counter``, ``latency_ms`` or ``value``.
    name : str
        Metric name.
    labels : dict[str, str]
        Bounded label set supplied with the call.
    value : float | None
        Observed value, or ``None`` for a latency whose elapsed time is not
        deterministic.
    """

    kind: str
    name: str
    labels: dict[str, str]
    value: float | None


@dc.dataclass(slots=True)
class RecordingMetrics:
    """Value-metrics fake that captures every emission in call order."""

    observations: list[MetricObservation] = dc.field(default_factory=list)

    def increment_counter(
        self,
        name: str,
        *,
        labels: cabc.Mapping[str, str],
    ) -> None:
        """Capture one counter increment."""
        self.observations.append(MetricObservation("counter", name, dict(labels), 1.0))

    def observe_latency_ms(
        self,
        name: str,
        value: float,
        *,
        labels: cabc.Mapping[str, str],
    ) -> None:
        """Capture a latency observation without pinning its elapsed value."""
        _ = value
        self.observations.append(
            MetricObservation("latency_ms", name, dict(labels), None)
        )

    def observe_value(
        self,
        name: str,
        value: float,
        *,
        labels: cabc.Mapping[str, str],
    ) -> None:
        """Capture one scalar value observation."""
        self.observations.append(MetricObservation("value", name, dict(labels), value))
