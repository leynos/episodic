"""Unit tests for the Chrono spoken-runtime estimator."""

import pytest

from episodic.qa.chrono import (
    ChronoEstimatorConfig,
    ChronoEstimatorMetadata,
    ChronoEvaluationRequest,
    ChronoRuntimeEstimate,
    ChronoRuntimeEstimator,
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
        ChronoEstimatorConfig(**kwargs)


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
    ],
)
def test_chrono_metadata_rejects_negative_counts(
    field_name: str,
    field_value: int,
) -> None:
    """Reject impossible metadata counts."""
    kwargs = {
        "estimator_name": "chrono-naive-word-count",
        "estimator_version": "1",
        "input_character_count": 10,
        "spoken_word_count": 3,
        "words_per_minute": 150,
    }
    kwargs[field_name] = field_value

    with pytest.raises(ValueError, match=field_name):
        ChronoEstimatorMetadata(**kwargs)


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
        script_tei_xml=(
            "<TEI><text><body><div type='script'>"
            "<sp><speaker>Host</speaker><p>Hello there, welcome today.</p></sp>"
            "<sp><speaker>Guest</speaker><p>This is a short reply.</p></sp>"
            "</div></body></text></TEI>"
        )
    )

    result = ChronoRuntimeEstimator().estimate(request)

    assert result.estimated_seconds == 4
    assert result.metadata.spoken_word_count == 9
    assert result.metadata.words_per_minute == 150
    assert result.metadata.estimator_name == "chrono-naive-word-count"
    assert result.metadata.estimator_version == "1"
    assert result.metadata.input_character_count == len(request.script_tei_xml)


def test_chrono_estimator_ignores_markup_only_script() -> None:
    """Markup without spoken text should produce a zero-second estimate."""
    request = ChronoEvaluationRequest(
        script_tei_xml="<TEI><text><body><sp><speaker>Host</speaker></sp></body></text></TEI>"
    )

    result = ChronoRuntimeEstimator().estimate(request)

    assert result.estimated_seconds == 0
    assert result.metadata.spoken_word_count == 0
    assert result.metadata.input_character_count == len(request.script_tei_xml)


def test_chrono_estimator_does_not_double_count_nested_spoken_elements() -> None:
    """Nested spoken TEI elements should count only once."""
    request = ChronoEvaluationRequest(
        script_tei_xml=(
            "<TEI><text><body><sp><p>outer words "
            "<seg>nested words</seg></p></sp></body></text></TEI>"
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
        script_tei_xml=(
            "<TEI><text><body><sp><p>one two three</p></sp></body></text></TEI>"
        )
    )

    result = ChronoRuntimeEstimator(config=config).estimate(request)

    assert result.estimated_seconds == 3
    assert result.metadata.estimator_version == "2"
    assert result.metadata.words_per_minute == 60
