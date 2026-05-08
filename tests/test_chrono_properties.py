"""Property tests for Chrono spoken-runtime invariants."""

import re

import hypothesis.strategies as st
from hypothesis import given

from episodic.qa.chrono import ChronoEvaluationRequest, ChronoRuntimeEstimator

_SIMPLE_WORDS = st.lists(
    st.from_regex(r"[A-Za-z][A-Za-z0-9'-]*", fullmatch=True),
    max_size=50,
)


def _script_from_words(words: list[str]) -> str:
    return f"<TEI><text><body><sp><p>{' '.join(words)}</p></sp></body></text></TEI>"


@given(words=_SIMPLE_WORDS)
def test_estimated_seconds_are_never_negative(words: list[str]) -> None:
    """Any generated simple dialogue should produce a non-negative estimate."""
    result = ChronoRuntimeEstimator().estimate(
        ChronoEvaluationRequest(script_tei_xml=_script_from_words(words))
    )

    assert result.estimated_seconds >= 0


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

    assert combined.estimated_seconds >= prefix.estimated_seconds


@given(words=_SIMPLE_WORDS)
def test_reported_word_count_matches_naive_tokenizer(words: list[str]) -> None:
    """Reported word count should equal the accepted simple-token count."""
    script = _script_from_words(words)
    result = ChronoRuntimeEstimator().estimate(
        ChronoEvaluationRequest(script_tei_xml=script)
    )

    assert result.metadata.spoken_word_count == len(
        re.findall(r"[A-Za-z][A-Za-z0-9'-]*", " ".join(words))
    )
