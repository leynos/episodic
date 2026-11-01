"""Exit-code and configuration coverage for the QA retrieval CLI.

Each case pins one failure path: an unusable invocation, an unusable base URL,
an error envelope, a transport failure, or a throttle. Rendering and request
shaping live in ``tests/test_qa_cli.py``.
"""

import httpx
import pytest

from episodic.cli import main
from episodic.cli.errors import ApiUnavailableError, InvalidConfigError
from tests.qa_cli_fixtures import (
    EPISODE_ID,
    PAGE,
    canned,
    clean_environment,  # ruff: ignore[unused-import]  # An autouse fixture pytest needs in this module.
    list_arguments,
)

_CONNECTION_REFUSED = "connection refused"


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


def test_unauthenticated_response_names_the_missing_token(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Without a configured token, a 401 explains how to supply one."""
    transport, _ = canned(
        {"code": "unauthorized", "message": "Authorization is required."},
        status=401,
    )

    exit_code = main(list_arguments(), transport=transport)

    captured = capsys.readouterr()
    assert exit_code == 1, captured.err
    assert "EPISODIC_API_TOKEN" in captured.err, captured.err


def test_configured_token_suppresses_the_missing_token_hint(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A rejected but present token is not reported as missing."""
    transport, _ = canned(
        {"code": "unauthorized", "message": "Authorization is required."},
        status=401,
    )

    exit_code = main(
        ["--token", "rejected", *list_arguments()],
        transport=transport,
    )

    captured = capsys.readouterr()
    assert exit_code == 1, captured.err
    assert "EPISODIC_API_TOKEN" not in captured.err, captured.err


@pytest.mark.parametrize(
    "token",
    ["placeholder-café", "placeholder\tvalue"],
    ids=["non-ascii", "control-character"],
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


def test_unreachable_api_maps_to_exit_three(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A transport failure is reported as an unreachable API."""

    def handle(request: httpx.Request) -> httpx.Response:
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


def test_base_url_with_embedded_credentials_is_rejected(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A password in the URL is refused and never echoed back."""
    transport, recorded = canned(PAGE)
    embedded = "-".join(("not", "a", "real", "credential"))

    exit_code = main(
        [
            "--base-url",
            f"https://scribe:{embedded}@api.example.test",
            *list_arguments(),
        ],
        transport=transport,
    )

    captured = capsys.readouterr()
    assert exit_code == InvalidConfigError.exit_code == 2, captured.err
    assert recorded.seen == [], recorded.seen
    assert "remove the embedded credentials" in captured.err, captured.err
    assert embedded not in captured.err, captured.err


def test_base_url_query_string_is_not_echoed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A query string can carry a secret, so the message omits it."""
    transport, recorded = canned(PAGE)
    marker = "-".join(("not", "a", "real", "key"))

    exit_code = main(
        [
            "--base-url",
            f"https://api.example.test?apikey={marker}",
            *list_arguments(),
        ],
        transport=transport,
    )

    captured = capsys.readouterr()
    assert exit_code == InvalidConfigError.exit_code == 2, captured.err
    assert recorded.seen == [], recorded.seen
    assert "remove the query string and fragment" in captured.err, captured.err
    assert marker not in captured.err, captured.err


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
