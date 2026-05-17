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
    _ceil_seconds,
    _compute_estimated_seconds,
    _seconds_contract_holds,
)

_VALID_WORD_COUNTS = st.integers(min_value=0, max_value=sys.maxsize)
_VALID_WORDS_PER_MINUTE = st.integers(min_value=1, max_value=sys.maxsize)
_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _integer_ceiling_seconds(spoken_word_count: int, words_per_minute: int) -> int:
    """Return the independent integer form of ceil(n * 60 / wpm)."""
    return (spoken_word_count * 60 + words_per_minute - 1) // words_per_minute


class TestChronoContracts:
    """Contract and property coverage for Chrono duration arithmetic."""

    def test_ceil_seconds_matches_formula_for_boundary_inputs(self) -> None:
        """The formula helper should match the documented ceiling calculation."""
        assert _ceil_seconds(1, 150) == 1
        assert _ceil_seconds(150, 150) == 60
        assert _ceil_seconds(sys.maxsize, sys.maxsize) == 60
        assert _ceil_seconds(1, 10**400) == 1

    def test_compute_estimated_seconds_preserves_zero_identity(self) -> None:
        """Zero spoken words should produce a zero-second estimate."""
        assert _compute_estimated_seconds(0, 1) == 0
        assert _compute_estimated_seconds(0, sys.maxsize) == 0

    def test_compute_estimated_seconds_avoids_float_underflow(self) -> None:
        """Positive word counts should not round down under huge WPM configs."""
        assert _compute_estimated_seconds(1, 10**400) == 1

    def test_seconds_contract_holds_rejects_invalid_estimates(self) -> None:
        """The contract predicate should reject bad estimates."""
        assert not _seconds_contract_holds(0, 150, -1)
        assert not _seconds_contract_holds(0, 150, 1)
        assert not _seconds_contract_holds(150, 150, 0)
        assert not _seconds_contract_holds(150, 150, 59)

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
        spoken_word_count=_VALID_WORD_COUNTS,
        words_per_minute=_VALID_WORDS_PER_MINUTE,
    )
    def test_ceil_seconds_matches_ceiling_formula(
        self,
        spoken_word_count: int,
        words_per_minute: int,
    ) -> None:
        """The internal ceiling helper should match Chrono's arithmetic formula."""
        assert _ceil_seconds(spoken_word_count, words_per_minute) == (
            _integer_ceiling_seconds(spoken_word_count, words_per_minute)
        )

    @given(words_per_minute=_VALID_WORDS_PER_MINUTE)
    def test_compute_estimated_seconds_handles_zero_word_count(
        self,
        words_per_minute: int,
    ) -> None:
        """The public contract helper should preserve the zero-case identity."""
        assert _compute_estimated_seconds(0, words_per_minute) == 0

    @given(
        spoken_word_count=st.integers(min_value=1, max_value=sys.maxsize),
        words_per_minute=_VALID_WORDS_PER_MINUTE,
    )
    def test_compute_estimated_seconds_matches_formula_for_positive_counts(
        self,
        spoken_word_count: int,
        words_per_minute: int,
    ) -> None:
        """Positive word counts should use the exact documented ceiling formula."""
        assert _compute_estimated_seconds(
            spoken_word_count,
            words_per_minute,
        ) == _integer_ceiling_seconds(spoken_word_count, words_per_minute)

    @given(
        spoken_word_count=_VALID_WORD_COUNTS,
        words_per_minute=_VALID_WORDS_PER_MINUTE,
    )
    def test_compute_estimated_seconds_satisfies_postconditions(
        self,
        spoken_word_count: int,
        words_per_minute: int,
    ) -> None:
        """Computed estimates should satisfy the CrossHair postcondition predicate."""
        estimated_seconds = _compute_estimated_seconds(
            spoken_word_count,
            words_per_minute,
        )

        assert _seconds_contract_holds(
            spoken_word_count,
            words_per_minute,
            estimated_seconds,
        )

    @given(
        spoken_word_count=_VALID_WORD_COUNTS,
        words_per_minute=_VALID_WORDS_PER_MINUTE,
        estimated_seconds=st.integers(min_value=-sys.maxsize, max_value=sys.maxsize),
    )
    def test_seconds_contract_holds_matches_independent_postcondition(
        self,
        spoken_word_count: int,
        words_per_minute: int,
        estimated_seconds: int,
    ) -> None:
        """The predicate should encode the same postconditions CrossHair checks."""
        expected = (
            estimated_seconds >= 0
            and (spoken_word_count == 0) == (estimated_seconds == 0)
            and (
                spoken_word_count == 0
                or estimated_seconds
                == _integer_ceiling_seconds(spoken_word_count, words_per_minute)
            )
        )

        assert (
            _seconds_contract_holds(
                spoken_word_count,
                words_per_minute,
                estimated_seconds,
            )
            is expected
        )
