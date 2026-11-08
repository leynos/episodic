"""Exit-code and configuration coverage for the QA retrieval CLI.

Each case pins one failure path: an unusable invocation, an unusable base URL,
an error envelope, a transport failure, or a throttle. Rendering and request
shaping live in ``tests/test_qa_cli.py``.
"""

import dataclasses as dc

import httpx
import pytest

from episodic.cli import main
from episodic.cli.errors import ApiUnavailableError, InvalidConfigError
from tests.qa_cli_fixtures import (
    EPISODE_ID,
    PAGE,
    canned,
    list_arguments,
)

pytestmark = pytest.mark.usefixtures("clean_environment")

_CONNECTION_REFUSED = "connection refused"
_UNAUTHORIZED: dict[str, object] = {
    "code": "unauthorized",
    "message": "Authorization is required.",
}
_EMBEDDED_CREDENTIAL = "-".join(("not", "a", "real", "credential"))
_QUERY_SECRET = "-".join(("not", "a", "real", "key"))


def test_missing_episode_is_a_usage_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A missing required argument is reported as a usage error."""
    transport, recorded = canned(PAGE)

    exit_code = main(["qa", "evaluations", "list"], transport=transport)

    captured = capsys.readouterr()
    assert exit_code == 2, captured.err
    assert recorded.seen == [], recorded.seen
    assert not captured.out, captured.out
    assert "--episode" in captured.err, captured.err


def test_unknown_filter_value_is_a_usage_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An unknown enum value names the parameter and its choices."""
    transport, recorded = canned(PAGE)

    exit_code = main(list_arguments("--evaluator", "nonsuch"), transport=transport)

    captured = capsys.readouterr()
    assert exit_code == 2, captured.err
    assert recorded.seen == [], recorded.seen
    assert "--evaluator" in captured.err, captured.err


def test_error_envelope_maps_to_exit_one(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An error envelope prints its status and message."""
    transport, _ = canned(
        {
            "code": "qa_evaluation_not_found",
            "message": "QA evaluation not found.",
            "details": {"episode_id": EPISODE_ID},
        },
        status=404,
    )

    exit_code = main(list_arguments(), transport=transport)

    captured = capsys.readouterr()
    assert exit_code == 1, captured.err
    assert not captured.out, captured.out
    assert "404 QA evaluation not found." in captured.err, captured.err


@dc.dataclass(frozen=True, slots=True)
class _RejectionCase:
    """One rejected invocation and the output it must produce."""

    arguments: list[str]
    response: tuple[dict[str, object], int]
    expected_exit_code: int
    is_config_error: bool
    expected_fragment: str | None
    forbidden_fragment: str | None
    rejects_before_dispatch: bool


@pytest.mark.parametrize(
    "case",
    [
        _RejectionCase(
            list_arguments(),
            (_UNAUTHORIZED, 401),
            1,
            is_config_error=False,
            expected_fragment="EPISODIC_API_TOKEN",
            forbidden_fragment=None,
            rejects_before_dispatch=False,
        ),
        _RejectionCase(
            ["--token", "rejected", *list_arguments()],
            (_UNAUTHORIZED, 401),
            1,
            is_config_error=False,
            expected_fragment=None,
            forbidden_fragment="EPISODIC_API_TOKEN",
            rejects_before_dispatch=False,
        ),
        _RejectionCase(
            [
                "--base-url",
                f"https://scribe:{_EMBEDDED_CREDENTIAL}@api.example.test",
                *list_arguments(),
            ],
            (PAGE, 200),
            2,
            is_config_error=True,
            expected_fragment="remove the embedded credentials",
            forbidden_fragment=_EMBEDDED_CREDENTIAL,
            rejects_before_dispatch=True,
        ),
        _RejectionCase(
            [
                "--base-url",
                f"https://api.example.test?apikey={_QUERY_SECRET}",
                *list_arguments(),
            ],
            (PAGE, 200),
            2,
            is_config_error=True,
            expected_fragment="remove the query string and fragment",
            forbidden_fragment=_QUERY_SECRET,
            rejects_before_dispatch=True,
        ),
    ],
    ids=[
        "unauthenticated",
        "configured-token",
        "embedded-credentials",
        "query-string-secret",
    ],
)
def test_rejected_invocation_does_not_echo_secrets(
    capsys: pytest.CaptureFixture[str],
    case: _RejectionCase,
) -> None:
    """A rejected invocation reports its reason without echoing a secret."""
    payload, status = case.response
    transport, recorded = canned(payload, status=status)

    exit_code = main(case.arguments, transport=transport)

    captured = capsys.readouterr()
    if case.is_config_error:
        expected = InvalidConfigError.exit_code
        assert exit_code == expected == case.expected_exit_code, captured.err
    else:
        assert exit_code == case.expected_exit_code, captured.err
    if case.rejects_before_dispatch:
        assert recorded.seen == [], recorded.seen
    if case.expected_fragment is not None:
        assert case.expected_fragment in captured.err, captured.err
    if case.forbidden_fragment is not None:
        assert case.forbidden_fragment not in captured.err, captured.err


@pytest.mark.parametrize(
    "token",
    ["placeholder-café", "placeholder\tvalue", "placeholder ", " placeholder"],
    ids=["non-ascii", "control-character", "trailing-space", "leading-space"],
)
def test_unusable_token_is_a_usage_error(
    capsys: pytest.CaptureFixture[str],
    token: str,
) -> None:
    """A token no HTTP header can carry is rejected before dispatch."""
    transport, recorded = canned(PAGE)

    exit_code = main(["--token", token, *list_arguments()], transport=transport)

    captured = capsys.readouterr()
    assert exit_code == InvalidConfigError.exit_code == 2, captured.err
    assert recorded.seen == [], recorded.seen
    assert "printable ASCII" in captured.err, captured.err
    assert "placeholder" not in captured.err, captured.err
    assert "placeholder" not in captured.out, captured.out


def test_unreachable_api_maps_to_exit_three(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A transport failure is reported as an unreachable API."""

    def handle(request: httpx.Request) -> httpx.Response:
        """Raise a connection-refused error for the request.

        Raises
        ------
        httpx.ConnectError
            Always, with the connection-refused message.
        """
        raise httpx.ConnectError(_CONNECTION_REFUSED, request=request)

    exit_code = main(list_arguments(), transport=httpx.MockTransport(handle))

    captured = capsys.readouterr()
    assert exit_code == ApiUnavailableError.exit_code == 3, captured.err
    assert "Cannot reach the Episodic API" in captured.err, captured.err


def test_throttled_response_maps_to_exit_four(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A 429 reports the retry delay and exits four."""
    transport, _ = canned(
        {"code": "rate_limited", "message": "Too many requests."},
        status=429,
        headers={"Retry-After": "30"},
    )

    exit_code = main(list_arguments(), transport=transport)

    captured = capsys.readouterr()
    assert exit_code == 4, captured.err
    assert "retry after 30 seconds" in captured.err, captured.err


def test_throttled_response_repeats_an_http_date_retry_after(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """RFC 9110 also allows an HTTP-date, which carries no seconds unit."""
    retry_after = "Wed, 21 Oct 2015 07:28:00 GMT"
    transport, _ = canned(
        {"code": "rate_limited", "message": "Too many requests."},
        status=429,
        headers={"Retry-After": retry_after},
    )

    exit_code = main(list_arguments(), transport=transport)

    captured = capsys.readouterr()
    assert exit_code == 4, captured.err
    assert f"retry after {retry_after}" in captured.err, captured.err
    assert "GMT seconds" not in captured.err, captured.err


def test_unexpected_success_body_is_an_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A 2xx body without an items list is a failure, not an empty page."""
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, text="<html>proxy error</html>")
    )

    exit_code = main(list_arguments(), transport=transport)

    captured = capsys.readouterr()
    assert exit_code == 1, captured.err
    assert not captured.out, captured.out
    assert "unexpected response body" in captured.err, captured.err


@pytest.mark.parametrize(
    ("global_options", "expected_fragment"),
    [
        (["--base-url", "not a url"], "Invalid Episodic API URL"),
        (
            ["--base-url", "https://api.example.test?source=cli"],
            "remove the query string and fragment",
        ),
        (
            ["--base-url", "https://api.example.test?"],
            "remove the query string and fragment",
        ),
        (
            ["--base-url", "https://api.example.test#"],
            "remove the query string and fragment",
        ),
        (
            ["--base-url", "http://api.example.test", "--token", "secret-token"],
            "Refusing to send a bearer token",
        ),
    ],
    ids=[
        "malformed",
        "query-string",
        "bare-query-marker",
        "bare-fragment-marker",
        "token-over-remote-http",
    ],
)
def test_unusable_base_url_is_a_usage_error(
    capsys: pytest.CaptureFixture[str],
    global_options: list[str],
    expected_fragment: str,
) -> None:
    """An unusable base URL is a usage error and sends no request."""
    transport, recorded = canned(PAGE)

    exit_code = main([*global_options, *list_arguments()], transport=transport)

    captured = capsys.readouterr()
    assert exit_code == InvalidConfigError.exit_code == 2, captured.err
    assert recorded.seen == [], recorded.seen
    assert expected_fragment in captured.err, captured.err


@pytest.mark.parametrize("timeout", ["-1", "0", "nan", "inf"])
def test_unusable_timeout_is_a_usage_error(
    capsys: pytest.CaptureFixture[str],
    timeout: str,
) -> None:
    """A timeout the transport cannot use is a usage error, not a traceback."""
    transport, recorded = canned(PAGE)

    exit_code = main(
        ["--timeout", timeout, *list_arguments()],
        transport=transport,
    )

    captured = capsys.readouterr()
    assert exit_code == InvalidConfigError.exit_code == 2, captured.err
    assert recorded.seen == [], recorded.seen
    assert "positive, finite number of seconds" in captured.err, captured.err


def test_remote_https_base_url_with_token_is_allowed() -> None:
    """HTTPS carries the credential, so a remote endpoint is permitted."""
    transport, recorded = canned(PAGE)

    exit_code = main(
        [
            "--base-url",
            "https://api.example.test",
            "--token",
            "secret-token",
            *list_arguments(),
        ],
        transport=transport,
    )

    request = recorded.seen[0]
    assert exit_code == 0, request.url
    assert request.url.scheme == "https", request.url
    assert request.headers["Authorization"] == "Bearer secret-token", request.headers


def test_help_succeeds(capsys: pytest.CaptureFixture[str]) -> None:
    """``--help`` prints usage and exits zero."""
    exit_code = main(["--help"])

    captured = capsys.readouterr()
    assert exit_code == 0, captured.out
    assert "Usage:" in captured.out, captured.out
