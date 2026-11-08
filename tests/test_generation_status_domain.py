"""Unit tests for generation-run and checkpoint status classification.

These tests pin which run and checkpoint statuses are terminal and the wire
values of the quality enums used by the no-QA slice.
"""

from episodic.canonical.domain import CheckpointStatus, GenerationRunStatus
from episodic.canonical.generation_quality import QaStatus, QualityMode


def test_generation_run_status_terminal_states_are_explicit() -> None:
    """Only completed run states should be terminal."""
    assert not GenerationRunStatus.PENDING.is_terminal(), (
        "PENDING must not be terminal."
    )
    assert not GenerationRunStatus.RUNNING.is_terminal(), (
        "RUNNING must not be terminal."
    )
    assert not GenerationRunStatus.PAUSED.is_terminal(), "PAUSED must not be terminal."
    assert GenerationRunStatus.SUCCEEDED.is_terminal(), "SUCCEEDED must be terminal."
    assert GenerationRunStatus.FAILED.is_terminal(), "FAILED must be terminal."
    assert GenerationRunStatus.CANCELLED.is_terminal(), "CANCELLED must be terminal."


def test_quality_enums_pin_no_qa_slice_values() -> None:
    """Quality metadata uses stable wire values for the no-QA slice."""
    assert QualityMode.DRAFT_WITHOUT_QA == "draft_without_qa", (
        f"expected draft_without_qa wire value, got {QualityMode.DRAFT_WITHOUT_QA!r}"
    )
    assert QaStatus.SKIPPED == "skipped", (
        f"expected skipped wire value, got {QaStatus.SKIPPED!r}"
    )


def test_checkpoint_status_terminal_states_are_explicit() -> None:
    """Only checkpoint end states should be terminal."""
    assert not CheckpointStatus.CREATED.is_terminal(), "CREATED must not be terminal."
    assert CheckpointStatus.RESPONDED.is_terminal(), "RESPONDED must be terminal."
    assert CheckpointStatus.TIMED_OUT.is_terminal(), "TIMED_OUT must be terminal."
    assert CheckpointStatus.CANCELLED.is_terminal(), "CANCELLED must be terminal."
