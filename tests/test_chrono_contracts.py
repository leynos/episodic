"""CrossHair contract verification for Chrono numeric arithmetic.

Run directly with:
    make crosshair

This module runs and documents the symbolic verification gate for
_compute_estimated_seconds as a Python-native alternative to Kani/Verus
bounded model-checking (which are Rust tools and cannot be applied to this
codebase).

Properties verified by CrossHair via SMT solving:
- Non-negativity: estimated_seconds >= 0 for all valid (n, wpm) pairs.
- Zero-case identity: n == 0 iff result == 0.
- Formula correctness: result == ceil(n / wpm * 60) for n > 0.

Preconditions that bound the input space (enforced by ChronoEstimatorConfig and
ChronoEstimatorMetadata __post_init__ guards):
- spoken_word_count >= 0
- words_per_minute > 0
"""

import subprocess  # noqa: S404  # Runs a fixed local CrossHair verification command.
import sys
from pathlib import Path

import hypothesis.strategies as st
import pytest
from hypothesis import given

from episodic.qa.chrono import (
    ChronoEstimatorConfig,
    ChronoEvaluationRequest,
    ChronoRuntimeEstimator,
)

_PUBLIC_API_WORD_COUNTS = st.integers(min_value=0, max_value=500)
_VALID_WORDS_PER_MINUTE = st.integers(min_value=1, max_value=sys.maxsize)
_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _integer_ceiling_seconds(spoken_word_count: int, words_per_minute: int) -> int:
    """Return the independent integer form of ceil(n * 60 / wpm)."""
    return (spoken_word_count * 60 + words_per_minute - 1) // words_per_minute


def _tei_document(body: str) -> str:
    """Wrap a TEI body fixture with the required document header."""
    return (
        "<TEI><teiHeader><fileDesc><title>Chrono contract test</title></fileDesc>"
        f"</teiHeader><text><body>{body}</body></text></TEI>"
    )


def _script_with_word_count(spoken_word_count: int) -> str:
    """Build a valid TEI script with the requested spoken word count."""
    spoken_text = " ".join(f"word{index}" for index in range(spoken_word_count))
    return _tei_document(f"<sp><p>{spoken_text}</p></sp>")


class TestChronoContracts:
    """Contract and property coverage for Chrono duration arithmetic."""

    @pytest.mark.parametrize(
        ("word_count", "words_per_minute", "expected_seconds"),
        [
            (1, 10**400, 1),
            (0, sys.maxsize, 0),
        ],
    )
    def test_estimate_matches_boundary_inputs(
        self,
        word_count: int,
        words_per_minute: int,
        expected_seconds: int,
    ) -> None:
        """The public estimator should match boundary duration cases."""
        request = ChronoEvaluationRequest(
            script_tei_xml=_script_with_word_count(word_count)
        )
        result = ChronoRuntimeEstimator(
            config=ChronoEstimatorConfig(words_per_minute=words_per_minute)
        ).estimate(request)

        assert result.estimated_seconds == expected_seconds
        assert result.metadata.spoken_word_count == word_count
        assert result.metadata.words_per_minute == words_per_minute

    @pytest.mark.crosshair
    def test_chrono_crosshair_contracts_pass(self) -> None:
        """CrossHair should verify Chrono's PEP 316 contracts automatically."""
        completed = subprocess.run(  # noqa: S603 - fixed argv, shell=False, no user input.
            [
                sys.executable,
                "-m",
                "crosshair",
                "check",
                "--analysis_kind=PEP316",
                "episodic/qa/chrono.py",
            ],
            cwd=_REPOSITORY_ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert completed.returncode == 0, (
            "CrossHair contract verification failed.\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )

    @given(
        spoken_word_count=_PUBLIC_API_WORD_COUNTS,
        words_per_minute=_VALID_WORDS_PER_MINUTE,
    )
    def test_estimate_matches_ceiling_formula(
        self,
        spoken_word_count: int,
        words_per_minute: int,
    ) -> None:
        """The public estimator should match Chrono's arithmetic formula."""
        request = ChronoEvaluationRequest(
            script_tei_xml=_script_with_word_count(spoken_word_count)
        )
        result = ChronoRuntimeEstimator(
            config=ChronoEstimatorConfig(words_per_minute=words_per_minute)
        ).estimate(request)

        assert result.estimated_seconds == (
            _integer_ceiling_seconds(spoken_word_count, words_per_minute)
        )
        assert result.metadata.spoken_word_count == spoken_word_count
        assert result.metadata.words_per_minute == words_per_minute

    @given(words_per_minute=_VALID_WORDS_PER_MINUTE)
    def test_estimate_handles_zero_word_count(
        self,
        words_per_minute: int,
    ) -> None:
        """The public estimator should preserve the zero-case identity."""
        request = ChronoEvaluationRequest(script_tei_xml=_script_with_word_count(0))
        result = ChronoRuntimeEstimator(
            config=ChronoEstimatorConfig(words_per_minute=words_per_minute)
        ).estimate(request)

        assert result.estimated_seconds == 0
        assert result.metadata.spoken_word_count == 0
        assert result.metadata.words_per_minute == words_per_minute

    @given(
        spoken_word_count=_PUBLIC_API_WORD_COUNTS,
        words_per_minute=_VALID_WORDS_PER_MINUTE,
    )
    def test_estimate_satisfies_postconditions(
        self,
        spoken_word_count: int,
        words_per_minute: int,
    ) -> None:
        """Public estimates should satisfy the CrossHair postcondition predicate."""
        request = ChronoEvaluationRequest(
            script_tei_xml=_script_with_word_count(spoken_word_count)
        )
        result = ChronoRuntimeEstimator(
            config=ChronoEstimatorConfig(words_per_minute=words_per_minute)
        ).estimate(request)
        estimated_seconds = result.estimated_seconds

        assert estimated_seconds >= 0
        assert (spoken_word_count == 0) == (estimated_seconds == 0)
        assert spoken_word_count == 0 or estimated_seconds == _integer_ceiling_seconds(
            spoken_word_count, words_per_minute
        )
