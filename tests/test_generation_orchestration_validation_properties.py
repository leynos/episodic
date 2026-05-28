"""Property tests for orchestration snapshot fixture validation boundaries.

These tests complement the Syrupy snapshot assertions by varying invalid DTO
inputs across ranges. They focus on timestamp, whitespace, and type validation
so fixture builders cannot silently accept malformed values before
serialisation.
"""

import re
import typing as typ

import hypothesis.strategies as st
import pytest
from hypothesis import given, settings

from episodic.orchestration import ActionKind, ModelTier, PlannedAction
from tests._generation_orchestration_snapshot_support import (
    _make_show_notes_entry,
    _PlannedActionKwargs,
)

_ISO_8601_DURATION_PATTERN = re.compile(
    r"^P(?=.*\d(?:\.\d+)?[YMWDHS])"
    r"(?:\d+(?:\.\d+)?W|"
    r"(?:\d+(?:\.\d+)?Y)?"
    r"(?:\d+(?:\.\d+)?M)?"
    r"(?:\d+(?:\.\d+)?D)?"
    r"(?:T"
    r"(?:\d+(?:\.\d+)?H)?"
    r"(?:\d+(?:\.\d+)?M)?"
    r"(?:\d+(?:\.\d+)?S)?"
    r")?"
    r")$"
)
_NON_ISO_TIMESTAMP_STRINGS = st.text(max_size=32).filter(
    lambda value: _ISO_8601_DURATION_PATTERN.fullmatch(value) is None
)
_WHITESPACE_STRINGS = st.text(alphabet=" \t\n\r\f\v", min_size=1, max_size=16)
_INVALID_DTO_FIELD_TYPES = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(),
    st.floats(allow_nan=False, allow_infinity=False),
    st.lists(st.text(max_size=8), max_size=3),
    st.dictionaries(st.text(max_size=8), st.integers(), max_size=3),
)


@given(timestamp=_NON_ISO_TIMESTAMP_STRINGS)
@settings(max_examples=50)
def test_show_notes_entry_rejects_arbitrary_non_iso8601_timestamps(
    timestamp: str,
) -> None:
    """Verify timestamp validation rejects arbitrary non-ISO strings."""
    with pytest.raises(ValueError, match="timestamp"):
        _make_show_notes_entry(timestamp=timestamp)


@given(timestamp=_INVALID_DTO_FIELD_TYPES)
@settings(max_examples=25)
def test_show_notes_entry_rejects_invalid_timestamp_types(timestamp: object) -> None:
    """Verify timestamp validation rejects non-string, non-None values."""
    if timestamp is None:
        timestamp = object()

    with pytest.raises(TypeError, match="expected string or bytes-like object"):
        _make_show_notes_entry(timestamp=typ.cast("str", timestamp))


@pytest.mark.parametrize(
    ("field_name", "error_match"),
    [
        ("rationale", "rationale must be a non-empty string"),
        ("required_inputs", "required_inputs must be a non-empty string"),
    ],
)
@given(value=_WHITESPACE_STRINGS)
@settings(max_examples=25)
def test_planned_action_rejects_arbitrary_whitespace_fields(
    field_name: str,
    error_match: str,
    value: str,
) -> None:
    """Verify PlannedAction rejects arbitrary whitespace-only field values."""
    kwargs: _PlannedActionKwargs = {
        "action_id": "a1",
        "action_kind": ActionKind.GENERATE_SHOW_NOTES,
        "rationale": "test",
        "model_tier": ModelTier.EXECUTION,
        "required_inputs": ("script_tei_xml",),
    }
    if field_name == "rationale":
        kwargs["rationale"] = value
    else:
        kwargs["required_inputs"] = (value,)

    with pytest.raises(ValueError, match=error_match):
        PlannedAction(**kwargs)


@pytest.mark.parametrize(
    ("field_name", "error_match"),
    [
        ("rationale", "rationale must be a non-empty string"),
        ("required_inputs", "required_inputs must be a non-empty string"),
    ],
)
@given(value=_INVALID_DTO_FIELD_TYPES)
@settings(max_examples=25)
def test_planned_action_rejects_invalid_field_types(
    field_name: str,
    error_match: str,
    value: object,
) -> None:
    """Verify PlannedAction rejects arbitrary invalid field types."""
    kwargs: _PlannedActionKwargs = {
        "action_id": "a1",
        "action_kind": ActionKind.GENERATE_SHOW_NOTES,
        "rationale": "test",
        "model_tier": ModelTier.EXECUTION,
        "required_inputs": ("script_tei_xml",),
    }
    if field_name == "rationale":
        kwargs["rationale"] = typ.cast("str", value)
    else:
        kwargs["required_inputs"] = typ.cast("tuple[str, ...]", (value,))

    with pytest.raises(ValueError, match=error_match):
        PlannedAction(**kwargs)
