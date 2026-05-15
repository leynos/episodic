"""Deterministic spoken-runtime estimation for TEI scripts."""

from __future__ import annotations

import dataclasses as dc
import logging
import math
import re
import time
import typing as typ

import tei_rapporteur as _tei

if typ.TYPE_CHECKING:
    from collections import abc as cabc

SPOKEN_WORD_REGEX = r"[A-Za-z][A-Za-z0-9'-]*"
_log = logging.getLogger(__name__)
_WORD_PATTERN = re.compile(SPOKEN_WORD_REGEX)
_DEFAULT_ESTIMATOR_NAME = "chrono-naive-word-count"
_DEFAULT_ESTIMATOR_VERSION = "1"
_DEFAULT_WORDS_PER_MINUTE = 150
_METRIC_EVALUATIONS = "chrono.runtime_estimator.evaluations"
_METRIC_LATENCY_MS = "chrono.runtime_estimator.latency_ms"


class ChronoMetricsPort(typ.Protocol):
    """Bounded-cardinality metrics sink for Chrono runtime estimation."""

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


@dc.dataclass(frozen=True, slots=True)
class _NoopChronoMetrics:
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


@dc.dataclass(frozen=True, slots=True)
class ChronoRuntimeEstimator:
    """Estimate anticipated spoken duration from TEI using a local heuristic.

    TEI validation and spoken-text extraction are delegated to tei-rapporteur.
    Chrono owns only the deterministic word-count and duration calculation.
    """

    config: ChronoEstimatorConfig = dc.field(default_factory=ChronoEstimatorConfig)
    metrics: ChronoMetricsPort = dc.field(default_factory=_NoopChronoMetrics)

    def estimate(self, request: ChronoEvaluationRequest) -> ChronoRuntimeEstimate:
        """Return a deterministic spoken-runtime estimate and metadata."""
        started = time.perf_counter()
        try:
            spoken_text = _extract_spoken_text(request.script_tei_xml)
        except ValueError:
            elapsed_ms = (time.perf_counter() - started) * 1000
            labels = {"outcome": "error", "error_type": "ValueError"}
            _log.warning(
                "Chrono TEI validation failed; input_character_count=%s",
                len(request.script_tei_xml),
                exc_info=True,
            )
            self.metrics.increment_counter(_METRIC_EVALUATIONS, labels=labels)
            self.metrics.observe_latency_ms(
                _METRIC_LATENCY_MS,
                elapsed_ms,
                labels=labels,
            )
            raise
        spoken_word_count = _count_spoken_words(spoken_text)
        if spoken_word_count == 0:
            _log.debug(
                "Chrono: no spoken words found",
                extra={"input_character_count": len(request.script_tei_xml)},
            )
        estimated_seconds = 0
        if spoken_word_count > 0:
            estimated_seconds = math.ceil(
                spoken_word_count / self.config.words_per_minute * 60
            )
        metadata = ChronoEstimatorMetadata(
            estimator_name=self.config.estimator_name,
            estimator_version=self.config.estimator_version,
            input_character_count=len(request.script_tei_xml),
            spoken_word_count=spoken_word_count,
            words_per_minute=self.config.words_per_minute,
        )
        elapsed_ms = (time.perf_counter() - started) * 1000
        labels = {"outcome": "success"}
        self.metrics.increment_counter(_METRIC_EVALUATIONS, labels=labels)
        self.metrics.observe_latency_ms(_METRIC_LATENCY_MS, elapsed_ms, labels=labels)
        return ChronoRuntimeEstimate(
            estimated_seconds=estimated_seconds,
            metadata=metadata,
        )

    async def evaluate(self, request: ChronoEvaluationRequest) -> ChronoRuntimeEstimate:
        """Async adapter method for orchestration code."""
        return self.estimate(request)
