"""Unit tests for Hecate subprocess invocation helpers."""

import subprocess  # ruff: ignore[suspicious-subprocess-import]  # Tests validate Hecate subprocess wrapping.
import typing as typ

import pytest
from architecture_hecate_config import (
    HECATE_TIMEOUT_SECONDS,
    REPO_ROOT,
    HecateInvocationError,
    run_hecate_fixture_check,
    run_hecate_production_check,
    write_fixture_config,
)

if typ.TYPE_CHECKING:
    import collections.abc as cabc
    from pathlib import Path


class _ErrorCase(typ.NamedTuple):
    """Pair a subprocess error factory with its expected match and cause type."""

    exception_factory: cabc.Callable[[list[str]], Exception]
    expected_match: str
    expected_cause_type: type[BaseException]


@pytest.mark.parametrize(
    "error_case",
    [
        pytest.param(
            _ErrorCase(
                exception_factory=lambda _cmd: OSError(),
                expected_match="failed to invoke Hecate for fixture package "
                "'allowed_case'",
                expected_cause_type=OSError,
            ),
            id="os_error",
        ),
        pytest.param(
            _ErrorCase(
                exception_factory=lambda cmd: subprocess.TimeoutExpired(
                    cmd,
                    HECATE_TIMEOUT_SECONDS,
                ),
                expected_match="Hecate command timed out for fixture package "
                "'allowed_case'",
                expected_cause_type=subprocess.TimeoutExpired,
            ),
            id="timeout",
        ),
    ],
)
def test_fixture_check_wraps_subprocess_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error_case: _ErrorCase,
) -> None:
    """Fixture checks annotate subprocess errors with package context."""
    config_path = write_fixture_config(tmp_path, "allowed_case")

    def raising_run(
        command: list[str],
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        """Raise the parametrised exception for the captured command."""
        raise error_case.exception_factory(command)

    monkeypatch.setattr(subprocess, "run", raising_run)

    with pytest.raises(
        HecateInvocationError,
        match=error_case.expected_match,
    ) as exc_info:
        run_hecate_fixture_check("allowed_case", config_path)

    assert isinstance(exc_info.value.__cause__, error_case.expected_cause_type), (
        "fixture invocation error cause must preserve the subprocess failure type"
    )


@pytest.mark.parametrize(
    "error_case",
    [
        pytest.param(
            _ErrorCase(
                exception_factory=lambda _cmd: subprocess.SubprocessError(),
                expected_match="failed to invoke Hecate for production packages",
                expected_cause_type=subprocess.SubprocessError,
            ),
            id="subprocess_error",
        ),
        pytest.param(
            _ErrorCase(
                exception_factory=lambda cmd: subprocess.TimeoutExpired(
                    cmd,
                    HECATE_TIMEOUT_SECONDS,
                ),
                expected_match="Hecate command timed out for production packages",
                expected_cause_type=subprocess.TimeoutExpired,
            ),
            id="timeout",
        ),
    ],
)
def test_production_check_wraps_subprocess_errors(
    monkeypatch: pytest.MonkeyPatch,
    error_case: _ErrorCase,
) -> None:
    """Production checks annotate subprocess errors with gate context."""

    def raising_run(
        command: list[str],
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        """Raise the parametrised exception for the captured command."""
        raise error_case.exception_factory(command)

    monkeypatch.setattr(subprocess, "run", raising_run)

    with pytest.raises(
        HecateInvocationError,
        match=error_case.expected_match,
    ) as exc_info:
        run_hecate_production_check()

    assert isinstance(exc_info.value.__cause__, error_case.expected_cause_type), (
        "production invocation error cause must preserve the subprocess failure type"
    )


@pytest.mark.parametrize("output_format", ["text", "json"])
def test_fixture_check_uses_injected_python_and_explicit_arguments(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    output_format: typ.Literal["text", "json"],
) -> None:
    """Fixture checks construct an isolated Hecate command."""
    config_path = write_fixture_config(tmp_path, "allowed_case")
    captured_command: list[str] = []

    def capture_run(
        command: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        """Record the command, check its keyword arguments and return success."""
        captured_command.extend(command)
        assert kwargs == {
            "check": False,
            "capture_output": True,
            "text": True,
            "timeout": HECATE_TIMEOUT_SECONDS,
            "cwd": REPO_ROOT,
        }, "fixture subprocess arguments must match the Hecate command contract"
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(subprocess, "run", capture_run)

    run_hecate_fixture_check(
        "allowed_case",
        config_path,
        python_executable="/custom/python",
        output_format=output_format,
    )

    expected_command = [
        "/custom/python",
        "-m",
        "hecate",
        "check",
        "--config",
        str(config_path),
        "--package",
        "tests.fixtures.architecture.allowed_case",
        "--root",
        str(REPO_ROOT / "tests/fixtures/architecture/allowed_case"),
        "--format",
        output_format,
    ]
    assert captured_command == expected_command, (
        "fixture Hecate command must include the requested output format"
    )


def test_production_check_uses_injected_python(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Production checks keep the executable substitutable."""
    captured_command: list[str] = []

    def capture_run(
        command: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        """Record the command, check its keyword arguments and return success."""
        captured_command.extend(command)
        assert kwargs == {
            "check": False,
            "capture_output": True,
            "text": True,
            "timeout": HECATE_TIMEOUT_SECONDS,
            "cwd": REPO_ROOT,
        }, "production subprocess arguments must match the Hecate command contract"
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(subprocess, "run", capture_run)

    run_hecate_production_check(python_executable="/custom/python")

    assert captured_command == ["/custom/python", "-m", "hecate", "check"], (
        "production Hecate command must use the injected Python executable"
    )
