"""Property tests for redacted authorization route labels."""

import enum

import hypothesis.strategies as st
from hypothesis import given

from episodic.api.authorization_observability import (
    _AUTHORIZATION_LOG_METHODS,
    _AUTHORIZATION_LOG_RESOURCE_LABELS,
    _OTHER_AUTHORIZATION_LOG_METHOD,
    _UNKNOWN_AUTHORIZATION_LOG_RESOURCE,
    _authorization_decision_label,
    _authorization_method_label,
    _authorization_route_label,
)

_LOG_SENSITIVE_CATEGORIES = ("Cc", "Cf", "Zl", "Zp")
_ALLOWED_ROUTE_LABELS = frozenset((
    *_AUTHORIZATION_LOG_RESOURCE_LABELS.values(),
    _UNKNOWN_AUTHORIZATION_LOG_RESOURCE,
))
_ALLOWED_METHOD_LABELS = frozenset((
    *_AUTHORIZATION_LOG_METHODS,
    _OTHER_AUTHORIZATION_LOG_METHOD,
))


class _ForgedAuthorizationDecision(enum.StrEnum):
    """Represent an enum value that must not become an audit label."""

    INJECTED = "forged\nBearer sensitive-token"


@given(log_character=st.characters(categories=_LOG_SENSITIVE_CATEGORIES))
def test_authorization_route_labels_omit_sensitive_path_characters(
    log_character: str,
) -> None:
    """Dynamic path content cannot enter labels, even for Unicode controls."""
    actual = _authorization_route_label(f"/v1/series-profiles/{log_character}")

    assert actual == "/v1/series-profiles", (
        f"expected the fixed resource label, got {actual!r}"
    )


@given(log_character=st.characters(categories=_LOG_SENSITIVE_CATEGORIES))
def test_authorization_route_labels_redact_sensitive_first_segment(
    log_character: str,
) -> None:
    """Sensitive characters in the resource segment yield an unknown label."""
    actual = _authorization_route_label(f"/v1/series-profiles{log_character}")

    assert actual == _UNKNOWN_AUTHORIZATION_LOG_RESOURCE, (
        f"expected the unknown resource label, got {actual!r}"
    )


@given(path_text=st.text())
def test_authorization_route_labels_are_always_allow_listed(path_text: str) -> None:
    """Arbitrary first-segment text can only yield a fixed route label."""
    actual = _authorization_route_label(f"/v1/{path_text}")

    assert actual in _ALLOWED_ROUTE_LABELS, f"unexpected label {actual!r}"


@given(method=st.text())
def test_authorization_method_labels_are_always_allow_listed(method: str) -> None:
    """Arbitrary method tokens can only yield a fixed method label."""
    actual = _authorization_method_label(method)

    assert actual in _ALLOWED_METHOD_LABELS, f"unexpected label {actual!r}"


def test_authorization_decision_labels_reject_unknown_enum_values() -> None:
    """An unexpected enum value cannot inject text into authorization logs."""
    actual = _authorization_decision_label(_ForgedAuthorizationDecision.INJECTED)

    assert actual == "unknown", f"unexpected decision label {actual!r}"
