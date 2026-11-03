"""Credential-handling coverage for the QA retrieval CLI.

A bearer token must never reach standard output or standard error, whether it
arrives on the command line, in the environment, or inside a transport error
message.
"""

import httpx
import pytest

from episodic.cli import main
from episodic.cli.client import TOKEN_ENV
from episodic.cli.errors import ApiUnavailableError, InvalidConfigError
from tests.qa_cli_fixtures import PAGE, canned, list_arguments

pytestmark = pytest.mark.usefixtures("clean_environment")

# A padded header value rather than a credential: the surrounding spaces are
# the thing under test.
_PADDED_VALUE = " placeholder "


def test_environment_token_with_surrounding_space_is_a_usage_error(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A whitespace-padded environment token fails before any request."""
    monkeypatch.setenv(TOKEN_ENV, _PADDED_VALUE)
    transport, recorded = canned(PAGE)

    exit_code = main(list_arguments(), transport=transport)

    captured = capsys.readouterr()
    assert exit_code == InvalidConfigError.exit_code == 2, captured.err
    assert recorded.seen == [], recorded.seen
    assert "printable ASCII" in captured.err, captured.err
    assert "placeholder" not in captured.err, captured.err
    assert "placeholder" not in captured.out, captured.out


def test_transport_error_cannot_echo_the_configured_token(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A protocol error that quotes the header must not expose the token."""
    token = "-".join(("not", "a", "real", "credential"))

    def reject_header(request: httpx.Request) -> httpx.Response:
        """Fail the way h11 does when it refuses a header value."""
        message = f"Illegal header value b'Bearer {token} '"
        raise httpx.LocalProtocolError(message)

    exit_code = main(
        ["--token", token, *list_arguments()],
        transport=httpx.MockTransport(reject_header),
    )

    captured = capsys.readouterr()
    assert exit_code == ApiUnavailableError.exit_code == 3, captured.err
    assert "[redacted]" in captured.err, captured.err
    assert token not in captured.err, captured.err
    assert token not in captured.out, captured.out
