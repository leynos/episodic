"""Recording observability doubles shared by the test suite.

Tests assert on captured spans, so these adapters keep their state public.
They perform no I/O and are imported by tests only.
"""

import dataclasses as dc
import typing as typ

if typ.TYPE_CHECKING:
    from collections import abc as cabc

    from episodic.observability._ports import SpanHandle


@dc.dataclass(slots=True)
class RecordedSpan:
    """Captured span data exposed by :class:`RecordingTracer` for tests."""

    name: str
    attributes: dict[str, str]
    is_completed: bool = False


@dc.dataclass(slots=True)
class _RecordingSpan:
    """Mark a recorded span complete when its context exits."""

    record: RecordedSpan

    def __enter__(self) -> typ.Self:
        """Enter the recording span context."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: object,
    ) -> bool:
        """Record completion without suppressing an operation exception."""
        del exc_type, exc_value, traceback
        self.record.is_completed = True
        return False

    def set_attribute(self, name: str, value: str) -> None:
        """Capture one attribute for deterministic assertions."""
        self.record.attributes[name] = value


@dc.dataclass(slots=True)
class RecordingTracer:
    """Test adapter that records spans and their completion state."""

    spans: list[RecordedSpan] = dc.field(default_factory=list)

    def start_span(
        self,
        name: str,
        *,
        attributes: cabc.Mapping[str, str],
    ) -> SpanHandle:
        """Record a span and return its completion context."""
        record = RecordedSpan(name=name, attributes=dict(attributes))
        self.spans.append(record)
        return _RecordingSpan(record)
