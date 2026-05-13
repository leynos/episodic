"""Unit tests for the Chrono spoken-runtime estimator."""

import asyncio
import dataclasses as dc
import typing as typ

import pytest

from episodic.qa.chrono import (
    ChronoEstimatorConfig,
    ChronoEstimatorMetadata,
    ChronoEvaluationRequest,
    ChronoRuntimeEstimate,
    ChronoRuntimeEstimator,
)


@dc.dataclass(slots=True)
class _FakeChronoMetrics:
    """Capture Chrono metrics for unit assertions."""

    counters: list[tuple[str, dict[str, str]]] = dc.field(default_factory=list)
    latencies: list[tuple[str, float, dict[str, str]]] = dc.field(default_factory=list)

    def increment_counter(
        self,
        name: str,
        *,
        labels: typ.Mapping[str, str],
    ) -> None:
        """Capture a counter increment."""
        self.counters.append((name, dict(labels)))

    def observe_latency_ms(
        self,
        name: str,
        value: float,
        *,
        labels: typ.Mapping[str, str],
    ) -> None:
        """Capture a latency observation."""
        self.latencies.append((name, value, dict(labels)))


def _tei_document(body: str) -> str:
    """Wrap a TEI body fixture with the required document header."""
    return (
        "<TEI><teiHeader><fileDesc><title>Chrono test</title></fileDesc>"
        f"</teiHeader><text><body>{body}</body></text></TEI>"
    )


def test_chrono_request_rejects_blank_script() -> None:
    """Reject blank TEI payloads at the contract boundary."""
    with pytest.raises(ValueError, match="script_tei_xml"):
        ChronoEvaluationRequest(script_tei_xml="   ")


@pytest.mark.parametrize(
    "field_name",
    ["estimator_name", "estimator_version"],
)
def test_chrono_config_rejects_blank_identity(field_name: str) -> None:
    """Reject blank estimator identity fields."""
    kwargs: dict[str, object] = {
        "estimator_name": "chrono-naive-word-count",
        "estimator_version": "1",
        "words_per_minute": 150,
    }
    kwargs[field_name] = "   "

    with pytest.raises(ValueError, match=field_name):
        ChronoEstimatorConfig(**typ.cast("typ.Any", kwargs))


@pytest.mark.parametrize("words_per_minute", [0, -1])
def test_chrono_config_rejects_non_positive_words_per_minute(
    words_per_minute: int,
) -> None:
    """Reject invalid speaking-rate values."""
    with pytest.raises(ValueError, match="words_per_minute"):
        ChronoEstimatorConfig(words_per_minute=words_per_minute)


@pytest.mark.parametrize(
    ("field_name", "field_value"),
    [
        ("input_character_count", -1),
        ("spoken_word_count", -1),
        ("estimator_name", ""),
        ("estimator_name", "   "),
        ("estimator_version", ""),
        ("estimator_version", "   "),
    ],
)
def test_chrono_metadata_rejects_invalid_field(
    field_name: str,
    field_value: object,
) -> None:
    """Reject invalid metadata field values at the contract boundary."""
    kwargs: dict[str, object] = {
        "estimator_name": "chrono-naive-word-count",
        "estimator_version": "1",
        "input_character_count": 10,
        "spoken_word_count": 3,
        "words_per_minute": 150,
    }
    kwargs[field_name] = field_value

    with pytest.raises(ValueError, match=field_name):
        ChronoEstimatorMetadata(**typ.cast("typ.Any", kwargs))


def test_chrono_runtime_estimate_rejects_negative_duration() -> None:
    """Reject impossible spoken durations."""
    metadata = ChronoEstimatorMetadata(
        estimator_name="chrono-naive-word-count",
        estimator_version="1",
        input_character_count=10,
        spoken_word_count=3,
        words_per_minute=150,
    )

    with pytest.raises(ValueError, match="estimated_seconds"):
        ChronoRuntimeEstimate(estimated_seconds=-1, metadata=metadata)


def test_chrono_estimator_returns_predictable_default_runtime() -> None:
    """Estimate spoken runtime from TEI dialogue using the default heuristic."""
    request = ChronoEvaluationRequest(
        script_tei_xml=_tei_document(
            "<div type='script'>"
            "<sp><speaker>Host</speaker><p>Hello there, welcome today.</p></sp>"
            "<sp><speaker>Guest</speaker><p>This is a short reply.</p></sp>"
            "</div>"
        )
    )

    result = ChronoRuntimeEstimator().estimate(request)

    assert result.estimated_seconds == 4
    assert result.metadata.spoken_word_count == 9
    assert result.metadata.words_per_minute == 150
    assert result.metadata.estimator_name == "chrono-naive-word-count"
    assert result.metadata.estimator_version == "1"
    assert result.metadata.input_character_count == len(request.script_tei_xml)


def test_chrono_estimator_records_success_metrics() -> None:
    """Record bounded success metrics around runtime estimation."""
    metrics = _FakeChronoMetrics()
    request = ChronoEvaluationRequest(
        script_tei_xml=_tei_document("<sp><p>Hello there.</p></sp>")
    )

    ChronoRuntimeEstimator(metrics=metrics).estimate(request)

    assert metrics.counters == [
        ("chrono.runtime_estimator.evaluations", {"outcome": "success"})
    ]
    assert len(metrics.latencies) == 1
    latency_name, latency_ms, labels = metrics.latencies[0]
    assert latency_name == "chrono.runtime_estimator.latency_ms"
    assert latency_ms >= 0
    assert labels == {"outcome": "success"}


def test_chrono_estimator_ignores_markup_only_script() -> None:
    """Markup without spoken text should produce a zero-second estimate."""
    request = ChronoEvaluationRequest(
        script_tei_xml=_tei_document("<sp><speaker>Host</speaker></sp>")
    )

    result = ChronoRuntimeEstimator().estimate(request)

    assert result.estimated_seconds == 0
    assert result.metadata.spoken_word_count == 0
    assert result.metadata.input_character_count == len(request.script_tei_xml)


def test_chrono_estimator_does_not_double_count_nested_spoken_elements() -> None:
    """Nested spoken TEI elements should count only once."""
    request = ChronoEvaluationRequest(
        script_tei_xml=_tei_document(
            "<sp><p>outer words <seg>nested words</seg></p></sp>"
        )
    )

    result = ChronoRuntimeEstimator().estimate(request)

    assert result.metadata.spoken_word_count == 4
    assert result.estimated_seconds == 2


def test_chrono_estimator_uses_custom_metadata() -> None:
    """Carry custom estimator identity and speaking rate into result metadata."""
    config = ChronoEstimatorConfig(
        estimator_name="chrono-naive-word-count",
        estimator_version="2",
        words_per_minute=60,
    )
    request = ChronoEvaluationRequest(
        script_tei_xml=_tei_document("<sp><p>one two three</p></sp>")
    )

    result = ChronoRuntimeEstimator(config=config).estimate(request)

    assert result.estimated_seconds == 3
    assert result.metadata.estimator_version == "2"
    assert result.metadata.words_per_minute == 60


@pytest.mark.asyncio
async def test_chrono_estimator_async_evaluate_matches_sync_estimate() -> None:
    """Async evaluate() should produce the same result as sync estimate()."""
    config = ChronoEstimatorConfig(
        estimator_name="chrono-naive-word-count",
        estimator_version="2",
        words_per_minute=60,
    )
    request = ChronoEvaluationRequest(
        script_tei_xml=_tei_document("<sp><p>one two three</p></sp>")
    )
    estimator = ChronoRuntimeEstimator(config=config)

    sync_result = estimator.estimate(request)
    async_result = await estimator.evaluate(request)

    assert async_result == sync_result, (
        "evaluate() must delegate to estimate() and return an identical result"
    )


@pytest.mark.asyncio
async def test_chrono_estimator_handles_concurrent_evaluations() -> None:
    """A shared estimator should handle concurrent immutable requests."""
    estimator = ChronoRuntimeEstimator()
    requests = [
        ChronoEvaluationRequest(
            script_tei_xml=_tei_document(
                f"<sp><p>{' '.join(['word'] * (index + 1))}</p></sp>"
            )
        )
        for index in range(5)
    ]
    expected_results = [estimator.estimate(request) for request in requests]

    results = await asyncio.gather(
        *(estimator.evaluate(request) for request in requests)
    )

    assert results == expected_results, (
        "concurrent evaluate() calls must match independent sync estimates"
    )
    assert [result.metadata.input_character_count for result in results] == [
        len(request.script_tei_xml) for request in requests
    ], "concurrent results must preserve per-request metadata"


@pytest.mark.parametrize(
    ("script_tei_xml", "message"),
    [
        ("hello world broken <p", "syntax error"),
        (
            _tei_document("<foo>bad</foo>"),
            "unsupported TEI body element",
        ),
    ],
)
def test_chrono_estimator_propagates_tei_validation_errors(
    script_tei_xml: str,
    message: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Malformed or unsupported TEI should fail instead of being counted."""
    request = ChronoEvaluationRequest(script_tei_xml=script_tei_xml)
    metrics = _FakeChronoMetrics()
    warnings: list[tuple[str, tuple[object, ...], dict[str, object]]] = []

    def capture_warning(
        msg: str,
        *args: object,
        **kwargs: object,
    ) -> None:
        warnings.append((msg, args, kwargs))

    monkeypatch.setattr("episodic.qa.chrono._log.warning", capture_warning)
    with pytest.raises(ValueError, match=message):
        ChronoRuntimeEstimator(metrics=metrics).estimate(request)

    assert warnings == [
        (
            "Chrono TEI validation failed; input_character_count=%s",
            (len(script_tei_xml),),
            {"exc_info": True},
        )
    ]
    assert metrics.counters == [
        (
            "chrono.runtime_estimator.evaluations",
            {"outcome": "error", "error_type": "ValueError"},
        )
    ]
    assert len(metrics.latencies) == 1
    latency_name, latency_ms, labels = metrics.latencies[0]
    assert latency_name == "chrono.runtime_estimator.latency_ms"
    assert latency_ms >= 0
    assert labels == {"outcome": "error", "error_type": "ValueError"}


@pytest.mark.parametrize(
    ("tag", "content", "expected_words", "expected_seconds"),
    [
        ("ab", "one two three", 3, 2),
        ("seg", "four five", 2, 1),
        ("l", "six", 1, 1),
    ],
)
def test_chrono_estimator_counts_alternate_spoken_tags(
    tag: str,
    content: str,
    expected_words: int,
    expected_seconds: int,
) -> None:
    """Chrono must extract spoken text from <ab>, <seg>, and <l> elements."""
    xml = _tei_document(f"<div type='script'><{tag}>{content}</{tag}></div>")
    result = ChronoRuntimeEstimator().estimate(
        ChronoEvaluationRequest(script_tei_xml=xml)
    )
    assert result.metadata.spoken_word_count == expected_words, (
        f"expected {expected_words} words from <{tag}> element, "
        f"got {result.metadata.spoken_word_count}"
    )
    assert result.estimated_seconds == expected_seconds
