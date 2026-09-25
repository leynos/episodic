"""Tests for terminal generation-run lifecycle invariants."""

import dataclasses as dc
import datetime as dt
import re
import uuid

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from episodic.canonical.domain import GenerationRun, GenerationRunStatus
from episodic.canonical.generation_quality import QaStatus, QualityMode

NOW = dt.datetime(2026, 6, 4, 8, 0, tzinfo=dt.UTC)


def _pending_run() -> GenerationRun:
    """Build an otherwise valid pending generation run."""
    return GenerationRun(
        id=uuid.uuid7(),
        episode_id=uuid.uuid7(),
        source_bundle_id=uuid.uuid7(),
        actor="editor@example.com",
        status=GenerationRunStatus.PENDING,
        current_node=None,
        budget_snapshot={"limit": 10},
        configuration={"model": "gpt-4.1"},
        created_at=NOW,
        updated_at=NOW,
        started_at=None,
        ended_at=None,
        error_message=None,
        quality_mode=QualityMode.DRAFT_WITHOUT_QA,
        qa_status=QaStatus.SKIPPED,
        skip_qa_rationale="No-QA vertical-slice draft.",
    )


@pytest.mark.parametrize(
    ("current_node", "ended_at", "message"),
    [
        ("complete", NOW, "terminal generation runs must not have a current node"),
        (None, None, "terminal generation runs must have an end time"),
    ],
)
def test_generation_run_rejects_invalid_terminal_lifecycle(
    current_node: str | None,
    ended_at: dt.datetime | None,
    message: str,
) -> None:
    """Terminal runs require an end time and clear their active node."""
    with pytest.raises(ValueError, match=message):
        dc.replace(
            _pending_run(),
            status=GenerationRunStatus.SUCCEEDED,
            current_node=current_node,
            ended_at=ended_at,
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("ended_at", "", "ended_at must be a datetime."),
        ("ended_at", 0.0, "ended_at must be a datetime."),
        ("current_node", 0, "current_node must be a string."),
        ("current_node", b"draft", "current_node must be a string."),
    ],
)
def test_generation_run_rejects_mistyped_lifecycle_fields(
    field: str,
    value: object,
    message: str,
) -> None:
    """A wrong type is a TypeError, raised before the value checks.

    ``ended_at`` is checked on every run, not just terminal ones, and the type
    checks run first so a mistyped field cannot be reported as an invalid
    value instead.
    """
    with pytest.raises(TypeError, match=re.escape(message)):
        dc.replace(_pending_run(), **{field: value})


def test_generation_run_accepts_a_valid_terminal_run() -> None:
    """A correctly typed terminal run satisfies the lifecycle invariant."""
    run = dc.replace(
        _pending_run(),
        status=GenerationRunStatus.SUCCEEDED,
        current_node=None,
        ended_at=NOW,
    )
    assert run.status is GenerationRunStatus.SUCCEEDED
    assert run.ended_at == NOW
    assert run.current_node is None


def test_terminal_type_error_outranks_the_node_value_error() -> None:
    """A mistyped terminal node reports the type, not the lifecycle rule."""
    with pytest.raises(TypeError, match=re.escape("current_node must be a string.")):
        dc.replace(
            _pending_run(),
            status=GenerationRunStatus.SUCCEEDED,
            current_node=0,
            ended_at=NOW,
        )


TERMINAL_STATUSES = (
    GenerationRunStatus.SUCCEEDED,
    GenerationRunStatus.FAILED,
    GenerationRunStatus.CANCELLED,
)
NON_TERMINAL_STATUSES = (
    GenerationRunStatus.PENDING,
    GenerationRunStatus.RUNNING,
    GenerationRunStatus.PAUSED,
)


@settings(max_examples=25)
@given(status=st.sampled_from(TERMINAL_STATUSES))
def test_every_terminal_status_accepts_a_cleared_lifecycle(
    status: GenerationRunStatus,
) -> None:
    """Every terminal state accepts a cleared node and a set end time."""
    run = dc.replace(
        _pending_run(),
        status=status,
        current_node=None,
        ended_at=NOW,
    )
    assert run.status is status
    assert run.current_node is None
    assert run.ended_at == NOW


@settings(max_examples=25)
@given(
    status=st.sampled_from(TERMINAL_STATUSES),
    active_node=st.text(min_size=1),
)
def test_every_terminal_status_rejects_an_active_node(
    status: GenerationRunStatus,
    active_node: str,
) -> None:
    """A terminal run may not retain an active node, whatever the label."""
    with pytest.raises(
        ValueError,
        match="terminal generation runs must not have a current node",
    ):
        dc.replace(
            _pending_run(),
            status=status,
            current_node=active_node,
            ended_at=NOW,
        )


@settings(max_examples=25)
@given(status=st.sampled_from(TERMINAL_STATUSES))
def test_every_terminal_status_requires_an_end_time(
    status: GenerationRunStatus,
) -> None:
    """A terminal run always carries the end time that closed it."""
    with pytest.raises(ValueError, match="terminal generation runs must have an end time"):
        dc.replace(
            _pending_run(),
            status=status,
            current_node=None,
            ended_at=None,
        )


@settings(max_examples=25)
@given(
    status=st.sampled_from(NON_TERMINAL_STATUSES),
    ended_at=st.one_of(st.none(), st.just(NOW)),
)
def test_non_terminal_statuses_keep_their_lifecycle_unchanged(
    status: GenerationRunStatus,
    ended_at: dt.datetime | None,
) -> None:
    """A non-terminal run is untouched by the terminal lifecycle rule."""
    run = dc.replace(_pending_run(), status=status, ended_at=ended_at)
    assert run.status is status
    assert run.ended_at == ended_at
