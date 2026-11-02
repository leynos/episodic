"""Property tests for authorization path log escaping."""

import hypothesis.strategies as st
from hypothesis import given

from episodic.api.authorization import _escape_path_for_log

_LOG_SENSITIVE_CATEGORIES = ("Cc", "Cf", "Zl", "Zp")


@given(log_character=st.characters(categories=_LOG_SENSITIVE_CATEGORIES))
def test_authorization_log_paths_escape_sensitive_unicode_characters(
    log_character: str,
) -> None:
    """Controls, formatting characters, and separators are escaped before logging."""
    escaped_character = log_character.encode("unicode_escape").decode("ascii")
    actual = _escape_path_for_log(log_character)

    assert actual == escaped_character, (
        f"expected escaped character {escaped_character!r}"
    )
