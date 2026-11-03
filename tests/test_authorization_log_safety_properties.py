"""Property tests for redacted authorization route labels."""

import hypothesis.strategies as st
from hypothesis import given

from episodic.api.authorization import _authorization_route_label

_LOG_SENSITIVE_CATEGORIES = ("Cc", "Cf", "Zl", "Zp")


@given(log_character=st.characters(categories=_LOG_SENSITIVE_CATEGORIES))
def test_authorization_route_labels_omit_sensitive_path_characters(
    log_character: str,
) -> None:
    """Dynamic path content cannot enter labels, even for Unicode controls."""
    actual = _authorization_route_label(f"/v1/series-profiles/{log_character}")

    assert actual == "/v1/series-profiles", (
        f"expected the fixed resource label, got {actual!r}"
    )
