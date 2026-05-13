"""Unit tests for Vidai Mock orchestration BDD helpers."""

from pathlib import Path

import pytest

from tests.steps.generation_orchestration_vidaimock import start_vidaimock_process
from tests.steps.test_generation_orchestration_steps import OrchestrationBDDContext


def test_start_vidaimock_process_fails_in_ci_when_executable_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fail the behavioural story in CI when Vidai Mock is unavailable."""
    monkeypatch.setenv("CI", "1")
    monkeypatch.setattr("shutil.which", lambda _: None)

    with pytest.raises(pytest.fail.Exception, match="vidaimock executable not found"):
        start_vidaimock_process(OrchestrationBDDContext(), config_dir=Path(), port=0)


def test_start_vidaimock_process_skips_locally_when_executable_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep the local developer skip when Vidai Mock is unavailable."""
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setattr("shutil.which", lambda _: None)

    with pytest.raises(pytest.skip.Exception, match="vidaimock executable not found"):
        start_vidaimock_process(OrchestrationBDDContext(), config_dir=Path(), port=0)
