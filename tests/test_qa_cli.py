"""Rendering and request-shaping coverage for the QA retrieval CLI.

The HTTP boundary is stubbed with ``httpx.MockTransport`` so each test observes
the request the CLI builds and controls the response it renders. Exit-code
mapping and configuration failures live in ``tests/test_qa_cli_errors.py``;
behavioural coverage through the real application lives in
``tests/steps/test_qa_cli_steps.py``.
"""

import json
import typing as typ

import pytest

from episodic.cli import main
from episodic.cli.rendering import render_json, render_table
from tests.qa_cli_fixtures import (
    EMPTY_PAGE,
    EPISODE_ID,
    PAGE,
    canned,
    list_arguments,
    redacted,
)

if typ.TYPE_CHECKING:
    from syrupy.assertion import SnapshotAssertion

pytestmark = pytest.mark.usefixtures("clean_environment")


def test_table_renders_a_page(snapshot: SnapshotAssertion) -> None:
    """The table carries every evaluation and a page summary."""
    assert render_table(redacted(PAGE)) == snapshot, (
        "the page table must match its snapshot"
    )


def test_table_renders_an_empty_page(snapshot: SnapshotAssertion) -> None:
    """An empty page still prints its header and a zero summary."""
    assert render_table(redacted(EMPTY_PAGE)) == snapshot, (
        "an empty page must still match its snapshot"
    )


def test_json_prints_the_envelope(snapshot: SnapshotAssertion) -> None:
    """The JSON rendering is the envelope, indented and newline-terminated."""
    rendered = render_json(redacted(PAGE))
    assert rendered.endswith("}\n"), rendered
    assert rendered == snapshot, "the JSON envelope must match its snapshot"


def test_list_prints_the_table(capsys: pytest.CaptureFixture[str]) -> None:
    """The command prints the rendered table and exits zero."""
    transport, _ = canned(PAGE)

    exit_code = main(list_arguments(), transport=transport)

    captured = capsys.readouterr()
    assert exit_code == 0, "listing must succeed"
    assert not captured.err, captured.err
    assert "pedante" in captured.out, captured.out
    assert "3 of 3 evaluations" in captured.out, captured.out


def test_list_prints_json_on_request(capsys: pytest.CaptureFixture[str]) -> None:
    """``--format json`` prints the envelope the API returned."""
    transport, _ = canned(PAGE)

    exit_code = main(list_arguments("--format", "json"), transport=transport)

    captured = capsys.readouterr()
    assert exit_code == 0, "JSON output must succeed"
    assert json.loads(captured.out)["total"] == 3, captured.out


def test_filters_and_pagination_reach_the_api(
    snapshot: SnapshotAssertion,
) -> None:
    """Every supplied filter becomes a query parameter."""
    transport, recorded = canned(PAGE)

    main(
        list_arguments(
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
    transport, recorded = canned(PAGE)

    main(["--token", "secret-token", *list_arguments()], transport=transport)

    assert recorded.seen[0].headers["Authorization"] == "Bearer secret-token", (
        recorded.seen[0].headers
    )


def test_default_endpoint_is_localhost() -> None:
    """With nothing configured, requests target the local API."""
    transport, recorded = canned(PAGE)

    main(list_arguments(), transport=transport)

    request = recorded.seen[0]
    assert request.url.host == "127.0.0.1", str(request.url)
    assert request.url.port == 8000, str(request.url)
    assert "Authorization" not in request.headers, request.headers


def test_environment_supplies_the_endpoint_and_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The environment provides the defaults an option can override."""
    monkeypatch.setenv("EPISODIC_API_URL", "https://api.example.test:9000")
    monkeypatch.setenv("EPISODIC_API_TOKEN", "environment-token")
    transport, recorded = canned(PAGE)

    main(list_arguments(), transport=transport)
    main(
        [
            "--base-url",
            "https://cli.example.test",
            "--token",
            "cli-token",
            *list_arguments(),
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
