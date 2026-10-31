"""Unit and snapshot coverage for the QA retrieval CLI.

The HTTP boundary is stubbed with ``httpx.MockTransport`` so each test observes
the request the CLI builds and controls the response it renders. Behavioural
coverage through the real application lives in
``tests/steps/test_qa_cli_steps.py``.
"""

import dataclasses as dc
import json
import typing as typ

import httpx
import pytest

from episodic.cli import main
from episodic.cli.client import ApiUnavailableError, InvalidConfigError
from episodic.cli.rendering import render_json, render_table
from tests.snapshot_redaction import redact_snapshot_uuids

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from syrupy.assertion import SnapshotAssertion

EPISODE_ID = "0199a0c2-0000-7000-8000-000000000010"
_CONNECTION_REFUSED = "connection refused"

_PEDANTE = {
    "id": "0199a0c2-0000-7000-8000-000000000001",
    "episode_id": EPISODE_ID,
    "generation_run_id": "0199a0c2-0000-7000-8000-000000000020",
    "evaluator": "pedante",
    "evaluator_version": "pedante-1.0",
    "artefact_schema_version": 1,
    "compliance_policy_version": 1,
    "compliance_status": "non_compliant",
    "summary": "Three claims were checked.",
    "rubric_score": None,
    "runtime_estimate_seconds": None,
    "finding_count": 3,
    "evaluator_metadata": {},
    "evaluated_at": "2026-10-31T10:00:00+00:00",
}
_CHRONO = {
    **_PEDANTE,
    "id": "0199a0c2-0000-7000-8000-000000000002",
    "evaluator": "chrono",
    "evaluator_version": "chrono-1.0",
    "compliance_status": "not_applicable",
    "summary": "Estimated 412 seconds of speech.",
    "runtime_estimate_seconds": 412,
    "finding_count": 0,
    "evaluated_at": "2026-10-31T10:05:00+00:00",
}
_ANTHEM = {
    **_PEDANTE,
    "id": "0199a0c2-0000-7000-8000-000000000003",
    "evaluator": "anthem",
    "evaluator_version": "anthem-1.0",
    "compliance_status": "errored",
    "summary": "Anthem did not respond before the deadline.",
    "finding_count": 0,
    "evaluated_at": "2026-10-31T10:10:00+00:00",
}
_PAGE: dict[str, object] = {
    "items": [_ANTHEM, _CHRONO, _PEDANTE],
    "limit": 20,
    "offset": 0,
    "total": 3,
}
_EMPTY_PAGE: dict[str, object] = {
    "items": [],
    "limit": 20,
    "offset": 0,
    "total": 0,
}


@dc.dataclass(slots=True)
class RecordedRequests:
    """Requests the stubbed transport received."""

    seen: list[httpx.Request] = dc.field(default_factory=list)


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate the CLI from the operator's own API settings."""
    monkeypatch.delenv("EPISODIC_API_URL", raising=False)
    monkeypatch.delenv("EPISODIC_API_TOKEN", raising=False)


def _canned(
    payload: object,
    *,
    status: int = 200,
    headers: cabc.Mapping[str, str] | None = None,
) -> tuple[httpx.MockTransport, RecordedRequests]:
    """Return a transport answering every request with one JSON body."""
    recorded = RecordedRequests()

    def handle(request: httpx.Request) -> httpx.Response:
        recorded.seen.append(request)
        return httpx.Response(status, json=payload, headers=headers)

    return httpx.MockTransport(handle), recorded


def _list_arguments(*extra: str) -> list[str]:
    """Return the arguments for a listing of the fixture episode."""
    return ["qa", "evaluations", "list", EPISODE_ID, *extra]


def _redacted(payload: dict[str, object]) -> dict[str, object]:
    """Return ``payload`` with the incidental UUIDs replaced."""
    return typ.cast("dict[str, object]", redact_snapshot_uuids(payload))


def test_table_renders_a_page(snapshot: SnapshotAssertion) -> None:
    """The table carries every evaluation and a page summary."""
    assert render_table(_redacted(_PAGE)) == snapshot, (
        "the page table must match its snapshot"
    )


def test_table_renders_an_empty_page(snapshot: SnapshotAssertion) -> None:
    """An empty page still prints its header and a zero summary."""
    assert render_table(_redacted(_EMPTY_PAGE)) == snapshot, (
        "an empty page must still match its snapshot"
    )


def test_json_prints_the_envelope(snapshot: SnapshotAssertion) -> None:
    """The JSON rendering is the envelope, indented and newline-terminated."""
    rendered = render_json(_redacted(_PAGE))
    assert rendered.endswith("}\n"), rendered
    assert rendered == snapshot, "the JSON envelope must match its snapshot"


def test_list_prints_the_table(capsys: pytest.CaptureFixture[str]) -> None:
    """The command prints the rendered table and exits zero."""
    transport, _ = _canned(_PAGE)

    exit_code = main(_list_arguments(), transport=transport)

    captured = capsys.readouterr()
    assert exit_code == 0, "listing must succeed"
    assert not captured.err, captured.err
    assert "pedante" in captured.out, captured.out
    assert "3 of 3 evaluations" in captured.out, captured.out


def test_list_prints_json_on_request(capsys: pytest.CaptureFixture[str]) -> None:
    """``--format json`` prints the envelope the API returned."""
    transport, _ = _canned(_PAGE)

    exit_code = main(_list_arguments("--format", "json"), transport=transport)

    captured = capsys.readouterr()
    assert exit_code == 0, "JSON output must succeed"
    assert json.loads(captured.out)["total"] == 3, captured.out


def test_filters_and_pagination_reach_the_api(snapshot: SnapshotAssertion) -> None:
    """Every supplied filter becomes a query parameter."""
    transport, recorded = _canned(_PAGE)

    main(
        _list_arguments(
            "--evaluator",
            "pedante",
            "--compliance-status",
            "non_compliant",
            "--limit",
            "5",
            "--offset",
            "10",
        ),
        transport=transport,
    )

    request = recorded.seen[0]
    assert request.url.path == f"/v1/episodes/{EPISODE_ID}/qa-evaluations", request.url
    assert dict(request.url.params) == snapshot, dict(request.url.params)


def test_token_is_sent_as_a_bearer_credential() -> None:
    """An explicit token becomes the bearer credential."""
    transport, recorded = _canned(_PAGE)

    main(["--token", "secret-token", *_list_arguments()], transport=transport)

    assert recorded.seen[0].headers["Authorization"] == "Bearer secret-token", (
        recorded.seen[0].headers
    )


def test_default_endpoint_is_localhost() -> None:
    """With nothing configured, requests target the local API."""
    transport, recorded = _canned(_PAGE)

    main(_list_arguments(), transport=transport)

    request = recorded.seen[0]
    assert request.url.host == "127.0.0.1", str(request.url)
    assert request.url.port == 8000, str(request.url)
    assert "Authorization" not in request.headers, request.headers


def test_environment_supplies_the_endpoint_and_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The environment provides the defaults an option can override."""
    monkeypatch.setenv("EPISODIC_API_URL", "http://api.example.test:9000")
    monkeypatch.setenv("EPISODIC_API_TOKEN", "environment-token")
    transport, recorded = _canned(_PAGE)

    main(_list_arguments(), transport=transport)
    main(
        [
            "--base-url",
            "http://cli.example.test",
            "--token",
            "cli-token",
            *_list_arguments(),
        ],
        transport=transport,
    )

    from_environment, from_options = recorded.seen
    assert from_environment.url.host == "api.example.test", from_environment.url
    assert from_environment.url.port == 9000, from_environment.url
    assert from_environment.headers["Authorization"] == "Bearer environment-token", (
        from_environment.headers
    )
    assert from_options.url.host == "cli.example.test", from_options.url
    assert from_options.headers["Authorization"] == "Bearer cli-token", (
        from_options.headers
    )


def test_missing_episode_is_a_usage_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A missing required argument is reported as a usage error."""
    transport, recorded = _canned(_PAGE)

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
    transport, recorded = _canned(_PAGE)

    exit_code = main(_list_arguments("--evaluator", "nonsuch"), transport=transport)

    captured = capsys.readouterr()
    assert exit_code == 2, captured.err
    assert recorded.seen == [], recorded.seen
    assert "--evaluator" in captured.err, captured.err


def test_error_envelope_maps_to_exit_one(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An error envelope prints its status and message."""
    transport, _ = _canned(
        {
            "code": "qa_evaluation_not_found",
            "message": "QA evaluation not found.",
            "details": {"episode_id": EPISODE_ID},
        },
        status=404,
    )

    exit_code = main(_list_arguments(), transport=transport)

    captured = capsys.readouterr()
    assert exit_code == 1, captured.err
    assert not captured.out, captured.out
    assert "404 QA evaluation not found." in captured.err, captured.err


def test_unauthenticated_response_names_the_missing_token(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Without a configured token, a 401 explains how to supply one."""
    transport, _ = _canned(
        {"code": "unauthorized", "message": "Authorization is required."},
        status=401,
    )

    exit_code = main(_list_arguments(), transport=transport)

    captured = capsys.readouterr()
    assert exit_code == 1, captured.err
    assert "EPISODIC_API_TOKEN" in captured.err, captured.err


def test_configured_token_suppresses_the_missing_token_hint(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A rejected but present token is not reported as missing."""
    transport, _ = _canned(
        {"code": "unauthorized", "message": "Authorization is required."},
        status=401,
    )

    exit_code = main(
        ["--token", "rejected", *_list_arguments()],
        transport=transport,
    )

    captured = capsys.readouterr()
    assert exit_code == 1, captured.err
    assert "EPISODIC_API_TOKEN" not in captured.err, captured.err


def test_unreachable_api_maps_to_exit_three(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A transport failure is reported as an unreachable API."""

    def handle(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(_CONNECTION_REFUSED, request=request)

    exit_code = main(_list_arguments(), transport=httpx.MockTransport(handle))

    captured = capsys.readouterr()
    assert exit_code == ApiUnavailableError.exit_code == 3, captured.err
    assert "Cannot reach the Episodic API" in captured.err, captured.err


def test_throttled_response_maps_to_exit_four(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A 429 reports the retry delay and exits four."""
    transport, _ = _canned(
        {"code": "rate_limited", "message": "Too many requests."},
        status=429,
        headers={"Retry-After": "30"},
    )

    exit_code = main(_list_arguments(), transport=transport)

    captured = capsys.readouterr()
    assert exit_code == 4, captured.err
    assert "retry after 30 seconds" in captured.err, captured.err


def test_unexpected_success_body_is_an_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A 2xx body without an items list is a failure, not an empty page."""
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, text="<html>proxy error</html>")
    )

    exit_code = main(_list_arguments(), transport=transport)

    captured = capsys.readouterr()
    assert exit_code == 1, captured.err
    assert not captured.out, captured.out
    assert "unexpected response body" in captured.err, captured.err


def test_malformed_base_url_is_a_usage_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An unusable base URL is reported without a traceback."""
    transport, recorded = _canned(_PAGE)

    exit_code = main(
        ["--base-url", "not a url", *_list_arguments()],
        transport=transport,
    )

    captured = capsys.readouterr()
    assert exit_code == InvalidConfigError.exit_code == 2, captured.err
    assert recorded.seen == [], recorded.seen
    assert "Invalid Episodic API URL" in captured.err, captured.err


def test_help_succeeds(capsys: pytest.CaptureFixture[str]) -> None:
    """``--help`` prints usage and exits zero."""
    exit_code = main(["--help"])

    captured = capsys.readouterr()
    assert exit_code == 0, captured.out
    assert "Usage:" in captured.out, captured.out
