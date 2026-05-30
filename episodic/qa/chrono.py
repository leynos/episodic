"""Chrono deterministic spoken-runtime estimation.

This module implements Chrono, the local QA component that estimates anticipated
spoken duration for TEI P5 podcast scripts. It delegates TEI parsing and
spoken-text extraction to ``tei-rapporteur`` and keeps Chrono's own policy
limited to deterministic token counting, duration calculation, metadata, and
operational reporting.

Main entry points:

- ``ChronoEvaluationRequest``: Input contract containing the TEI XML script to
  evaluate.
- ``ChronoRuntimeEstimator``: Primary estimator class. Call
  ``estimator.estimate(request)`` for synchronous domain use or
  ``await estimator.evaluate(request)`` when invoking through orchestration
  ports.
- ``ChronoRuntimeEstimate`` and ``ChronoEstimatorMetadata``: Output contracts
  carrying the predicted seconds and comparison metadata for later estimator
  versions.
- ``ChronoMetricsPort``: Feature-specific bounded-cardinality metrics port that
  narrows ``BoundedMetricsPort`` to Chrono's runtime estimator. The clock
  boundary reuses the canonical ``MonotonicClockPort`` from
  :mod:`episodic.observability` rather than declaring a parallel port.
- ``tokenize_spoken_words``: Public tokenizer helper used by property tests and
  callers that need to compare Chrono's simple word-count heuristic directly.

Chrono sits beside Pedante in the QA package but does not call an LLM. The
LangGraph adapter in ``episodic.qa.chrono_langgraph`` wraps this estimator for
graph execution, while this module owns the estimator contracts and local
runtime policy.
"""

import dataclasses as dc
import logging
import re
import typing as typ

import tei_rapporteur as _tei

from episodic.metrics_ports import BoundedMetricsPort, NoopBoundedMetrics
from episodic.observability import MonotonicClockPort, PerfCounterClock

SPOKEN_WORD_REGEX = r"[A-Za-z][A-Za-z0-9'-]*"
_log = logging.getLogger(__name__)
_WORD_PATTERN = re.compile(SPOKEN_WORD_REGEX)
_DEFAULT_ESTIMATOR_NAME = "chrono-naive-word-count"
_DEFAULT_ESTIMATOR_VERSION = "1"
_DEFAULT_WORDS_PER_MINUTE = 150
_METRIC_EVALUATIONS = "chrono.runtime_estimator.evaluations"
_METRIC_LATENCY_MS = "chrono.runtime_estimator.latency_ms"


class ChronoMetricsPort(BoundedMetricsPort, typ.Protocol):
    """Bounded-cardinality metrics sink for Chrono runtime estimation.

    This protocol narrows :class:`episodic.metrics_ports.BoundedMetricsPort` to
    name Chrono's metrics boundary; it does not introduce new methods. Adapters
    that satisfy ``BoundedMetricsPort`` therefore satisfy this port as well.
    """


@dc.dataclass(frozen=True, slots=True)
class _NoopChronoMetrics(NoopBoundedMetrics):
    """Default metrics sink used when no backend is wired."""


def _ensure_non_empty_string(value: str, field_name: str) -> None:
    """Reject blank string fields at Chrono contract boundaries."""
    if not value.strip():
        msg = f"{field_name} must be non-empty."
        raise ValueError(msg)


def _extract_spoken_text(script_tei_xml: str) -> str:
    """Extract spoken text through tei-rapporteur."""
    chunks: list[str] = []
    for segment in _tei.spoken_text_segments(script_tei_xml):
        stripped = segment.text.strip()
        if stripped:
            chunks.append(stripped)
    return " ".join(chunks)


def tokenize_spoken_words(spoken_text: str) -> list[str]:
    """Return deterministic simple word tokens for Chrono's naive heuristic."""
    return _WORD_PATTERN.findall(spoken_text)


def _count_spoken_words(spoken_text: str) -> int:
    """Count deterministic simple word tokens in extracted spoken text."""
    return len(tokenize_spoken_words(spoken_text))


@dc.dataclass(frozen=True, slots=True)
class ChronoEvaluationRequest:
    """Canonical Chrono request built from a TEI script.

    The estimator delegates TEI parsing and spoken-text extraction to
    tei-rapporteur, then applies Chrono's local word-count heuristic.
    """

    script_tei_xml: str

    def __post_init__(self) -> None:
        """Reject blank TEI payloads."""
        _ensure_non_empty_string(self.script_tei_xml, "script_tei_xml")


@dc.dataclass(frozen=True, slots=True)
class ChronoEstimatorConfig:
    """Configuration for Chrono's initial local heuristic."""

    estimator_name: str = _DEFAULT_ESTIMATOR_NAME
    estimator_version: str = _DEFAULT_ESTIMATOR_VERSION
    words_per_minute: int = _DEFAULT_WORDS_PER_MINUTE

    def __post_init__(self) -> None:
        """Reject invalid estimator identity or speaking-rate settings."""
        _ensure_non_empty_string(self.estimator_name, "estimator_name")
        _ensure_non_empty_string(self.estimator_version, "estimator_version")
        if self.words_per_minute <= 0:
            msg = "words_per_minute must be positive."
            raise ValueError(msg)


@dc.dataclass(frozen=True, slots=True)
class ChronoEstimatorMetadata:
    """Metadata that makes Chrono estimates comparable across implementations."""

    estimator_name: str
    estimator_version: str
    input_character_count: int
    spoken_word_count: int
    words_per_minute: int

    def __post_init__(self) -> None:
        """Reject invalid metadata values."""
        _ensure_non_empty_string(self.estimator_name, "estimator_name")
        _ensure_non_empty_string(self.estimator_version, "estimator_version")
        if self.input_character_count < 0:
            msg = "input_character_count must not be negative."
            raise ValueError(msg)
        if self.spoken_word_count < 0:
            msg = "spoken_word_count must not be negative."
            raise ValueError(msg)
        if self.words_per_minute <= 0:
            msg = "words_per_minute must be positive."
            raise ValueError(msg)


@dc.dataclass(frozen=True, slots=True)
class ChronoRuntimeEstimate:
    """Chrono's predicted spoken runtime for a script."""

    estimated_seconds: int
    metadata: ChronoEstimatorMetadata

    def __post_init__(self) -> None:
        """Reject impossible spoken-runtime values."""
        if self.estimated_seconds < 0:
            msg = "estimated_seconds must not be negative."
            raise ValueError(msg)


def _estimate_runtime(
    *,
    script_tei_xml: str,
    spoken_text: str,
    config: ChronoEstimatorConfig,
) -> ChronoRuntimeEstimate:
    """Build a deterministic Chrono estimate from extracted spoken text."""
    spoken_word_count = _count_spoken_words(spoken_text)
    estimated_seconds = _compute_estimated_seconds(
        spoken_word_count,
        config.words_per_minute,
    )
    metadata = ChronoEstimatorMetadata(
        estimator_name=config.estimator_name,
        estimator_version=config.estimator_version,
        input_character_count=len(script_tei_xml),
        spoken_word_count=spoken_word_count,
        words_per_minute=config.words_per_minute,
    )
    return ChronoRuntimeEstimate(
        estimated_seconds=estimated_seconds,
        metadata=metadata,
    )


def _compute_estimated_seconds(spoken_word_count: int, words_per_minute: int) -> int:
    """Compute estimated spoken duration in whole seconds.

    pre: spoken_word_count >= 0
    pre: words_per_minute > 0
    post: __return__ >= 0
    post: (spoken_word_count == 0) == (__return__ == 0)
    post: spoken_word_count==0 or __return__==-(-spoken_word_count*60//words_per_minute)
    """
    if spoken_word_count == 0:
        return 0
    return (spoken_word_count * 60 + words_per_minute - 1) // words_per_minute


@dc.dataclass(frozen=True, slots=True)
class ChronoRuntimeEstimator:
    """Estimate anticipated spoken duration from TEI using a local heuristic.

    TEI validation and spoken-text extraction are delegated to tei-rapporteur.
    Chrono owns only the deterministic word-count and duration calculation.
    """

    config: ChronoEstimatorConfig = dc.field(default_factory=ChronoEstimatorConfig)
    metrics: ChronoMetricsPort = dc.field(default_factory=_NoopChronoMetrics)
    clock: MonotonicClockPort = dc.field(default_factory=PerfCounterClock)

    def estimate(self, request: ChronoEvaluationRequest) -> ChronoRuntimeEstimate:
        """Return a deterministic spoken-runtime estimate and metadata."""
        started = self.clock.monotonic_seconds()
        try:
            spoken_text = _extract_spoken_text(request.script_tei_xml)
        except ValueError:
            self._record_validation_error(request, started=started)
            raise

        result = _estimate_runtime(
            script_tei_xml=request.script_tei_xml,
            spoken_text=spoken_text,
            config=self.config,
        )
        self._record_success(request, result=result, started=started)
        return result

    async def evaluate(self, request: ChronoEvaluationRequest) -> ChronoRuntimeEstimate:
        """Async adapter method for orchestration code."""
        return self.estimate(request)

    def _elapsed_ms_since(self, started: float) -> float:
        """Return elapsed wall-clock milliseconds via the injected clock."""
        return (self.clock.monotonic_seconds() - started) * 1000

    def _record_success(
        self,
        request: ChronoEvaluationRequest,
        *,
        result: ChronoRuntimeEstimate,
        started: float,
    ) -> None:
        """Record success-only side effects for the estimator boundary."""
        if result.metadata.spoken_word_count == 0:
            _log.debug(
                "Chrono: no spoken words found",
                extra={"input_character_count": len(request.script_tei_xml)},
            )
        labels = {"outcome": "success"}
        self.metrics.increment_counter(_METRIC_EVALUATIONS, labels=labels)
        self.metrics.observe_latency_ms(
            _METRIC_LATENCY_MS,
            self._elapsed_ms_since(started),
            labels=labels,
        )

    def _record_validation_error(
        self,
        request: ChronoEvaluationRequest,
        *,
        started: float,
    ) -> None:
        """Record validation-error side effects for the estimator boundary."""
        labels = {"outcome": "error", "error_type": "ValueError"}
        _log.warning(
            "Chrono TEI validation failed; input_character_count=%s",
            len(request.script_tei_xml),
            exc_info=True,
        )
        self.metrics.increment_counter(_METRIC_EVALUATIONS, labels=labels)
        self.metrics.observe_latency_ms(
            _METRIC_LATENCY_MS,
            self._elapsed_ms_since(started),
            labels=labels,
        )
