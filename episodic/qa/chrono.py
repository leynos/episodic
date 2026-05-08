"""Deterministic spoken-runtime estimation for TEI scripts."""

import dataclasses as dc
import math
import re
from xml.etree import ElementTree  # noqa: S405

_WORD_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9'-]*")
_DEFAULT_ESTIMATOR_NAME = "chrono-naive-word-count"
_DEFAULT_ESTIMATOR_VERSION = "1"
_DEFAULT_WORDS_PER_MINUTE = 150
_SPOKEN_TEXT_ELEMENTS = frozenset({"p", "ab", "seg", "l"})


def _ensure_non_empty_string(value: str, field_name: str) -> None:
    """Reject blank string fields at Chrono contract boundaries."""
    if value.strip() == "":
        msg = f"{field_name} must be non-empty."
        raise ValueError(msg)


def _local_name(tag: str) -> str:
    """Return an XML tag name without its namespace or Clark notation prefix."""
    return tag.rsplit("}", maxsplit=1)[-1]


def _extract_spoken_text_from_element(root: ElementTree.Element[str]) -> str:
    """Extract text from TEI elements that conventionally hold spoken prose."""
    chunks: list[str] = []

    def _walk(element: ElementTree.Element[str], *, inside_spoken: bool) -> None:
        is_spoken = _local_name(element.tag) in _SPOKEN_TEXT_ELEMENTS
        if is_spoken and not inside_spoken:
            text = " ".join(part.strip() for part in element.itertext() if part.strip())
            if text:
                chunks.append(text)
            inside_spoken = True
        if inside_spoken:
            return
        for child in element:
            _walk(child, inside_spoken=False)

    _walk(root, inside_spoken=False)
    return " ".join(chunks)


def _extract_spoken_text(script_tei_xml: str) -> str:
    """Extract spoken text from parseable TEI, or plain text from malformed input."""
    try:
        root = ElementTree.fromstring(script_tei_xml)  # noqa: S314
    except ElementTree.ParseError:
        return script_tei_xml
    return _extract_spoken_text_from_element(root)


def _count_spoken_words(spoken_text: str) -> int:
    """Count deterministic simple word tokens in extracted spoken text."""
    return len(_WORD_PATTERN.findall(spoken_text))


@dc.dataclass(frozen=True, slots=True)
class ChronoEvaluationRequest:
    """Canonical Chrono request built from a TEI script."""

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
    """Estimate anticipated spoken duration from TEI using a local heuristic."""

    config: ChronoEstimatorConfig = dc.field(default_factory=ChronoEstimatorConfig)

    def estimate(self, request: ChronoEvaluationRequest) -> ChronoRuntimeEstimate:
        """Return a deterministic spoken-runtime estimate and metadata."""
        spoken_text = _extract_spoken_text(request.script_tei_xml)
        spoken_word_count = _count_spoken_words(spoken_text)
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
        return ChronoRuntimeEstimate(
            estimated_seconds=estimated_seconds,
            metadata=metadata,
        )

    async def evaluate(self, request: ChronoEvaluationRequest) -> ChronoRuntimeEstimate:
        """Async adapter method for orchestration code."""
        return self.estimate(request)
