"""Property tests for Chrono spoken-runtime invariants."""

import hypothesis.strategies as st
from hypothesis import given

from episodic.qa.chrono import (
    SPOKEN_WORD_REGEX,
    ChronoEvaluationRequest,
    ChronoRuntimeEstimator,
    tokenize_spoken_words,
)

_SIMPLE_WORDS = st.lists(
    st.from_regex(SPOKEN_WORD_REGEX, fullmatch=True),
    min_size=1,
    max_size=50,
)


def _script_from_words(words: list[str]) -> str:
    return (
        "<TEI><teiHeader><fileDesc><title>Chrono property</title></fileDesc>"
        f"</teiHeader><text><body><sp><p>{' '.join(words)}</p></sp></body></text></TEI>"
    )


@given(words=_SIMPLE_WORDS)
def test_estimated_seconds_are_never_negative(words: list[str]) -> None:
    """Any generated simple dialogue should produce a non-negative estimate."""
    result = ChronoRuntimeEstimator().estimate(
        ChronoEvaluationRequest(script_tei_xml=_script_from_words(words))
    )

    assert result.estimated_seconds >= 0, (
        f"expected non-negative estimated_seconds, got {result.estimated_seconds}"
    )


@given(prefix_words=_SIMPLE_WORDS, suffix_words=_SIMPLE_WORDS)
def test_adding_spoken_words_does_not_reduce_runtime(
    prefix_words: list[str],
    suffix_words: list[str],
) -> None:
    """Adding spoken words should not reduce the estimate."""
    estimator = ChronoRuntimeEstimator()
    prefix = estimator.estimate(
        ChronoEvaluationRequest(script_tei_xml=_script_from_words(prefix_words))
    )
    combined = estimator.estimate(
        ChronoEvaluationRequest(
            script_tei_xml=_script_from_words([*prefix_words, *suffix_words])
        )
    )

    assert combined.estimated_seconds >= prefix.estimated_seconds, (
        "expected added spoken words not to reduce estimated_seconds: "
        f"prefix={prefix.estimated_seconds}, combined={combined.estimated_seconds}"
    )


@given(words=_SIMPLE_WORDS)
def test_reported_word_count_matches_naive_tokenizer(words: list[str]) -> None:
    """Reported word count should equal the accepted simple-token count."""
    script = _script_from_words(words)
    result = ChronoRuntimeEstimator().estimate(
        ChronoEvaluationRequest(script_tei_xml=script)
    )

    expected_word_count = len(tokenize_spoken_words(" ".join(words)))
    assert result.metadata.spoken_word_count == expected_word_count, (
        "expected reported spoken_word_count to match tokenizer count: "
        f"reported={result.metadata.spoken_word_count}, expected={expected_word_count}"
    )
