"""Property tests for redacted authorization route labels."""

import hypothesis.strategies as st
from hypothesis import given

from episodic.api.authorization import (
    _AUTHORIZATION_LOG_METHODS,
    _AUTHORIZATION_LOG_RESOURCE_LABELS,
    _OTHER_AUTHORIZATION_LOG_METHOD,
    _UNKNOWN_AUTHORIZATION_LOG_RESOURCE,
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


@given(log_character=st.characters(categories=_LOG_SENSITIVE_CATEGORIES))
def test_authorization_route_labels_omit_sensitive_path_characters(
    log_character: str,
) -> None:
    """Dynamic path content cannot enter labels, even for Unicode controls."""
    actual = _authorization_route_label(f"/v1/series-profiles/{log_character}")

    assert actual == "/v1/series-profiles", (
        f"expected the fixed resource label, got {actual!r}"
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
