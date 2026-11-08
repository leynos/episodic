"""Recording metrics and a deterministic clock for adapter observability tests."""

import itertools
import typing as typ

if typ.TYPE_CHECKING:
    import collections.abc as cabc


class RecordingMetrics:
    """Capture bounded counters and latency observations."""

    def __init__(self) -> None:
        """Create empty counter and latency stores."""
        self.counters: list[tuple[str, dict[str, str]]] = []
        self.latencies: list[tuple[str, float, dict[str, str]]] = []

    def increment_counter(
        self,
        name: str,
        *,
        labels: cabc.Mapping[str, str],
    ) -> None:
        """Record one counter increment."""
        self.counters.append((name, dict(labels)))

    def observe_latency_ms(
        self,
        name: str,
        value: float,
        *,
        labels: cabc.Mapping[str, str],
    ) -> None:
        """Record one latency observation."""
        self.latencies.append((name, value, dict(labels)))


class SteppingClock:
    """Return deterministic half-second monotonic steps."""

    def __init__(self) -> None:
        """Start the timestamp sequence at 1.0 seconds in half-second steps."""
        self._values = itertools.count(start=1.0, step=0.5)

    def monotonic_seconds(self) -> float:
        """Return the next configured timestamp."""
        return next(self._values)
