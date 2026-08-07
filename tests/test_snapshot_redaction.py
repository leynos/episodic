"""Tests for deterministic snapshot UUID redaction."""

import string
import typing as typ
import uuid

import hypothesis.strategies as st
import pytest
from hypothesis import given, settings

from tests.snapshot_redaction import redact_snapshot_uuids

type _Case = tuple[object, object]

# Excluding "-" keeps generated filler text incapable of forming a UUID, so a
# plain string is never redacted by accident.
_SAFE_ALPHABET = string.ascii_letters + string.digits + " _."
_PLAIN_STRINGS = st.text(alphabet=_SAFE_ALPHABET, max_size=12)
_SCALARS = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(),
    st.floats(allow_nan=False, allow_infinity=False),
)


def _unchanged(strategy: st.SearchStrategy[object]) -> st.SearchStrategy[_Case]:
    """Pair values with themselves for inputs redaction must not alter."""
    return strategy.map(lambda value: (value, value))


def _embedded_uuid_case(
    parts: tuple[str, uuid.UUID, str],
) -> _Case:
    """Build a string containing a UUID substring and its redacted form."""
    prefix, identifier, suffix = parts
    return (f"{prefix} {identifier} {suffix}", f"{prefix} <uuid> {suffix}")


_LEAVES = st.one_of(
    st.uuids().map(lambda identifier: (identifier, "<uuid>")),
    st.uuids().map(lambda identifier: (str(identifier), "<uuid>")),
    st.tuples(_PLAIN_STRINGS, st.uuids(), _PLAIN_STRINGS).map(_embedded_uuid_case),
    _unchanged(_PLAIN_STRINGS),
    _unchanged(_SCALARS),
)


def _list_case(items: list[_Case]) -> _Case:
    """Combine child cases into a list case."""
    return ([value for value, _ in items], [expected for _, expected in items])


def _tuple_case(items: list[_Case]) -> _Case:
    """Combine child cases into a tuple case."""
    return (
        tuple(value for value, _ in items),
        tuple(expected for _, expected in items),
    )


def _dict_case(items: dict[str, _Case]) -> _Case:
    """Combine child cases into a dictionary case keyed by plain strings."""
    return (
        {key: value for key, (value, _) in items.items()},
        {key: expected for key, (_, expected) in items.items()},
    )


def _containers(children: st.SearchStrategy[_Case]) -> st.SearchStrategy[_Case]:
    """Extend a case strategy with bounded list, tuple, and dictionary cases."""
    return st.one_of(
        st.lists(children, max_size=4).map(_list_case),
        st.lists(children, max_size=4).map(_tuple_case),
        # Keys stay plain so distinct keys cannot collide under redaction; the
        # collision guard has its own dedicated test.
        st.dictionaries(_PLAIN_STRINGS, children, max_size=4).map(_dict_case),
    )


_CASES = st.recursive(_LEAVES, _containers, max_leaves=12)


def _assert_redacted(actual: object, expected: object, path: str) -> None:
    """Assert *actual* matches *expected* in both container type and value."""
    assert type(actual) is type(expected), (
        f"redaction must preserve the type at {path}: "
        f"expected {type(expected).__name__}, got {type(actual).__name__}"
    )
    match (actual, expected):
        case (dict(), dict()):
            actual_mapping = typ.cast("dict[object, object]", actual)
            expected_mapping = typ.cast("dict[object, object]", expected)
            assert list(actual_mapping) == list(expected_mapping), (
                f"redaction must preserve dictionary keys at {path}"
            )
            for key, item in expected_mapping.items():
                _assert_redacted(actual_mapping[key], item, f"{path}[{key!r}]")
        case (list() | tuple(), list() | tuple()):
            actual_items = typ.cast("tuple[object, ...]", actual)
            expected_items = typ.cast("tuple[object, ...]", expected)
            assert len(actual_items) == len(expected_items), (
                f"redaction must preserve sequence length at {path}"
            )
            for index, item in enumerate(expected_items):
                _assert_redacted(actual_items[index], item, f"{path}[{index}]")
        case _:
            assert actual == expected, f"unexpected redacted value at {path}"


@given(_CASES)
@settings(max_examples=200)
def test_redact_snapshot_uuids_matches_expected_redaction(case: _Case) -> None:
    """Redaction replaces UUIDs and leaves every other value structurally intact."""
    value, expected = case

    _assert_redacted(redact_snapshot_uuids(value), expected, "$")


def test_redact_snapshot_uuids_redacts_dictionary_keys_and_values() -> None:
    """Dictionary UUID keys and values should both be redacted recursively."""
    identifier = uuid.UUID("018fdcf0-0000-7000-8000-000000000001")

    redacted = redact_snapshot_uuids({identifier: {str(identifier): identifier}})

    assert redacted == {"<uuid>": {"<uuid>": "<uuid>"}}, (
        "dictionary UUID keys and values must be redacted recursively"
    )


def test_redact_snapshot_uuids_rejects_colliding_dictionary_keys() -> None:
    """Distinct UUID keys must not be silently overwritten after redaction."""
    first = uuid.UUID("018fdcf0-0000-7000-8000-000000000001")
    second = uuid.UUID("018fdcf0-0000-7000-8000-000000000002")

    with pytest.raises(
        ValueError,
        match="distinct dictionary keys collide after UUID redaction",
    ):
        redact_snapshot_uuids({first: "first", second: "second"})
