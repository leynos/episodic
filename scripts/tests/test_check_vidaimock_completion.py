"""Tests for the fixture-completion oracle in the VidaiMock smoke test."""

from __future__ import annotations

import io
import typing as typ

import check_vidaimock_isolated as smoke
import pytest

if typ.TYPE_CHECKING:
    import subprocess
    from pathlib import Path

_BASE_URL = "http://127.0.0.1:4321/v1"
_FIXTURE_CONTENT = '{"plan_version": 1}'


def _completion_payload(
    *,
    content: str = _FIXTURE_CONTENT,
    model: str = smoke.PROVIDER_MODEL,
    prompt_tokens: object = smoke.PROVIDER_PROMPT_TOKENS,
    choices: list[object] | None = None,
    usage: object | None = None,
) -> dict[str, object]:
    """Build the completion shape returned by the fixture's template."""
    if choices is None:
        choices = [{"message": {"content": content}}]
    if usage is None:
        usage = {"prompt_tokens": prompt_tokens}
    return {"model": model, "choices": choices, "usage": usage}


def test_check_provider_round_trip_accepts_fixture_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The fixture marker, model echo, and planner usage all pass together."""
    calls: list[tuple[str, str]] = []

    def post_completion(base_url: str, *, model: str) -> dict[str, object]:
        calls.append((base_url, model))
        return _completion_payload()

    monkeypatch.setattr(smoke, "_post_completion", post_completion)

    smoke._check_provider_round_trip(_BASE_URL)

    assert calls == [(_BASE_URL, smoke.PROVIDER_MODEL)], (
        "the round trip must request the fixture's configured model."
    )


@pytest.mark.parametrize(
    ("payload", "diagnostic"),
    [
        pytest.param(
            _completion_payload(content="rendered output without the marker"),
            "does not carry 'plan_version'",
            id="missing-fixture-marker",
        ),
        pytest.param(
            _completion_payload(model="unexpected-model"),
            "instead of 'gpt-4.1'",
            id="wrong-echoed-model",
        ),
        pytest.param(
            _completion_payload(prompt_tokens=0),
            "planner branch did not render",
            id="wrong-prompt-token-count",
        ),
        pytest.param(
            _completion_payload(choices=[]),
            "completion carried no choices",
            id="missing-choices",
        ),
        pytest.param(
            _completion_payload(choices=[{"message": []}]),
            "completion choice",
            id="invalid-message-shape",
        ),
        pytest.param(
            _completion_payload(usage=[]),
            "usage must be a JSON object",
            id="invalid-usage-shape",
        ),
    ],
)
def test_check_provider_round_trip_rejects_incomplete_fixture_completion(
    monkeypatch: pytest.MonkeyPatch,
    payload: dict[str, object],
    diagnostic: str,
) -> None:
    """Each part of the fixture completion oracle has a failing regression."""

    def post_completion(base_url: str, *, model: str) -> dict[str, object]:
        del base_url, model
        return payload

    monkeypatch.setattr(smoke, "_post_completion", post_completion)

    with pytest.raises(smoke.SmokeTestError, match=diagnostic):
        smoke._check_provider_round_trip(_BASE_URL)


def test_main_cleans_up_server_after_successful_smoke_checks(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A successful smoke run still terminates its child and closes capture."""
    process = typ.cast("subprocess.Popen[str]", object())
    stderr_file = io.StringIO()
    server = smoke.VidaiMockServer(
        process=process,
        host="127.0.0.1",
        port=4321,
        label="test smoke server",
        stderr_file=stderr_file,
    )
    events: list[str] = []

    def find_executable(name: str) -> str:
        del name
        return "/opt/vidaimock"

    def configured_provider_names(config_dir: Path) -> list[str]:
        del config_dir
        return [smoke.PROVIDER_NAME]

    monkeypatch.setattr(smoke.shutil, "which", find_executable)
    monkeypatch.setattr(smoke, "_verify_startup", lambda: "/opt/vidaimock")
    monkeypatch.setattr(smoke, "_configured_provider_names", configured_provider_names)

    def start_server(launch: smoke.VidaiMockLaunch) -> smoke.VidaiMockServer:
        assert launch.executable == "/opt/vidaimock"
        events.append("start")
        return server

    def check_isolation(base_url: str, configured: list[str]) -> None:
        assert base_url == server.base_url
        assert configured == [smoke.PROVIDER_NAME]
        events.append("isolation")

    def check_completion(base_url: str) -> None:
        assert base_url == server.base_url
        events.append("completion")

    def clean_up(
        cleanup_process: subprocess.Popen[str],
        cleanup_stderr: io.StringIO | None,
    ) -> None:
        assert cleanup_process is process
        assert cleanup_stderr is stderr_file
        events.append("cleanup")

    monkeypatch.setattr(smoke, "start_vidaimock", start_server)
    monkeypatch.setattr(smoke, "_check_isolation", check_isolation)
    monkeypatch.setattr(smoke, "_check_provider_round_trip", check_completion)
    monkeypatch.setattr(smoke, "terminate_process_gracefully", clean_up)

    assert smoke.main() == 0, "all valid smoke checks must return success."
    assert events == ["start", "isolation", "completion", "cleanup"], (
        "main must clean up the server after both successful checks."
    )
    captured = capsys.readouterr()
    assert "OK: the installed vidaimock serves an isolated fixture provider" in (
        captured.out
    )
