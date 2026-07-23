"""Unit tests for Hecate architecture test helpers.

These tests keep fixture TOML generation, subprocess error handling, timeout
handling, and command construction local to `architecture_hecate_config.py`.
The broader architecture behaviour remains covered in
`tests/test_architecture_enforcement.py` and the BDD step tests.
"""

import subprocess  # noqa: S404  # Tests validate Hecate subprocess wrapping.
import tomllib
import typing as typ
from collections.abc import Callable  # noqa: ICN003, TC003
from pathlib import Path

import pytest
from architecture_hecate_config import (
    BARREL_OUTBOUND_FIXTURE,
    HECATE_TIMEOUT_SECONDS,
    REPO_ROOT,
    HecateInvocationError,
    run_hecate_fixture_check,
    run_hecate_production_check,
    write_fixture_config,
)


class _ErrorCase(typ.NamedTuple):
    exception_factory: Callable[[list[str]], Exception]
    expected_match: str
    expected_cause_type: type[BaseException]


def test_fixture_config_normal_fixture_excludes_package_barrel(
    tmp_path: Path,
) -> None:
    """Normal fixture configs classify only storage as the outbound adapter."""
    package_name = "api_imports_outbound_adapter"
    package = f"tests.fixtures.architecture.{package_name}"

    config = _read_fixture_config(tmp_path, package_name)

    assert _group_prefixes(config, "outbound_adapter") == [
        f"{package}.storage",
        f"{package}.adapter",
    ]


def test_fixture_config_barrel_fixture_includes_package_barrel(
    tmp_path: Path,
) -> None:
    """The barrel fixture config classifies the package barrel as outbound."""
    package = f"tests.fixtures.architecture.{BARREL_OUTBOUND_FIXTURE}"

    config = _read_fixture_config(tmp_path, BARREL_OUTBOUND_FIXTURE)

    assert _group_prefixes(config, "outbound_adapter") == [
        f"{package}.storage",
        f"{package}.adapter",
        package,
    ]


def test_fixture_config_writes_expected_toml_shape(tmp_path: Path) -> None:
    """Generated fixture configs expose Hecate's expected policy shape."""
    package_name = "allowed_case"
    package = f"tests.fixtures.architecture.{package_name}"

    config = _read_fixture_config(tmp_path, package_name)

    hecate_config = _hecate_config(config)
    assert hecate_config["root_packages"] == [package]
    assert hecate_config["default_rule_id"] == "ARCH001"
    assert _group_names(config) == [
        "composition_root",
        "domain",
        "orchestration_checkpoint",
        "orchestration_nodes",
        "orchestration_tasks",
        "orchestration",
        "application",
        "inbound_adapter",
        "outbound_adapter",
    ]
    assert _group_prefixes(config, "composition_root") == [f"{package}.runtime"]
    assert _group_allowed(config, "composition_root") == [
        "application",
        "composition_root",
        "domain",
        "inbound_adapter",
        "orchestration",
        "orchestration_checkpoint",
        "orchestration_nodes",
        "orchestration_tasks",
        "outbound_adapter",
    ]
    assert _group_prefixes(config, "domain") == [
        f"{package}.domain",
        f"{package}.worker.workloads",
    ]
    assert _group_allowed(config, "domain") == ["domain"]
    assert _group_prefixes(config, "orchestration_checkpoint") == [
        f"{package}.orchestration._checkpoint_payload",
        f"{package}.orchestration._checkpoint_dto",
        f"{package}.orchestration._payload_dto",
    ]
    assert _group_allowed(config, "orchestration_checkpoint") == [
        "orchestration_checkpoint",
        "domain",
    ]
    assert _group_prefixes(config, "orchestration_nodes") == [
        f"{package}.orchestration._graph_nodes",
    ]
    assert _group_allowed(config, "orchestration_nodes") == [
        "orchestration_nodes",
        "domain",
        "orchestration_checkpoint",
    ]
    assert _group_prefixes(config, "orchestration_tasks") == [
        f"{package}.worker.tasks",
    ]
    assert _group_allowed(config, "orchestration_tasks") == [
        "orchestration_tasks",
        "application",
        "domain",
    ]
    assert _group_prefixes(config, "orchestration") == [
        f"{package}.orchestration",
    ]
    assert _group_allowed(config, "orchestration") == [
        "orchestration",
        "application",
        "domain",
        "orchestration_checkpoint",
    ]
    assert _group_allowed(config, "application") == ["application", "domain"]
    assert _group_prefixes(config, "inbound_adapter") == [
        f"{package}.api",
        f"{package}.worker.topology",
    ]
    assert _group_allowed(config, "inbound_adapter") == [
        "inbound_adapter",
        "application",
        "domain",
    ]
    assert _group_allowed(config, "outbound_adapter") == [
        "outbound_adapter",
        "application",
        "domain",
    ]


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
        raise error_case.exception_factory(command)

    monkeypatch.setattr(subprocess, "run", raising_run)

    with pytest.raises(
        HecateInvocationError,
        match=error_case.expected_match,
    ) as exc_info:
        run_hecate_fixture_check("allowed_case", config_path)

    assert isinstance(exc_info.value.__cause__, error_case.expected_cause_type)


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
        raise error_case.exception_factory(command)

    monkeypatch.setattr(subprocess, "run", raising_run)

    with pytest.raises(
        HecateInvocationError,
        match=error_case.expected_match,
    ) as exc_info:
        run_hecate_production_check()

    assert isinstance(exc_info.value.__cause__, error_case.expected_cause_type)


def test_fixture_check_uses_injected_python_and_explicit_arguments(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fixture checks construct an isolated Hecate command."""
    config_path = write_fixture_config(tmp_path, "allowed_case")
    captured_command: list[str] = []

    def capture_run(
        command: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        captured_command.extend(command)
        assert kwargs == {
            "check": False,
            "capture_output": True,
            "text": True,
            "timeout": HECATE_TIMEOUT_SECONDS,
            "cwd": REPO_ROOT,
        }
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(subprocess, "run", capture_run)

    run_hecate_fixture_check(
        "allowed_case",
        config_path,
        python_executable="/custom/python",
    )

    assert captured_command == [
        "/custom/python",
        "-m",
        "hecate",
        "check",
        "--config",
        str(config_path),
        "--package",
        "tests.fixtures.architecture.allowed_case",
        "--root",
        str(
            Path(__file__).resolve().parent
            / "fixtures"
            / "architecture"
            / "allowed_case",
        ),
        "--format",
        "text",
    ]


def test_production_check_uses_injected_python(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Production checks keep the executable substitutable."""
    captured_command: list[str] = []

    def capture_run(
        command: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        captured_command.extend(command)
        assert kwargs == {
            "check": False,
            "capture_output": True,
            "text": True,
            "timeout": HECATE_TIMEOUT_SECONDS,
            "cwd": REPO_ROOT,
        }
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(subprocess, "run", capture_run)

    run_hecate_production_check(python_executable="/custom/python")

    assert captured_command == ["/custom/python", "-m", "hecate", "check"]


def _read_fixture_config(tmp_path: Path, package_name: str) -> dict[str, object]:
    """Write and parse the fixture Hecate config."""
    config_path = write_fixture_config(tmp_path, package_name)
    return tomllib.loads(config_path.read_text(encoding="utf-8"))


def _hecate_config(config: dict[str, object]) -> dict[str, object]:
    """Return the generated `[tool.hecate]` config table."""
    tool_config = typ.cast("dict[str, object]", config["tool"])
    return typ.cast("dict[str, object]", tool_config["hecate"])


def _group_prefixes(config: dict[str, object], group_name: str) -> list[str]:
    """Return prefixes for one generated Hecate group."""
    hecate_config = _hecate_config(config)
    groups = typ.cast("list[dict[str, object]]", hecate_config["groups"])
    for group in groups:
        if group["name"] == group_name:
            return typ.cast("list[str]", group["prefixes"])
    raise AssertionError(group_name)


def _group_names(config: dict[str, object]) -> list[str]:
    """Return generated Hecate group names in matching order."""
    hecate_config = _hecate_config(config)
    groups = typ.cast("list[dict[str, object]]", hecate_config["groups"])
    return [typ.cast("str", group["name"]) for group in groups]


def _group_allowed(config: dict[str, object], group_name: str) -> list[str]:
    """Return allowed dependency groups for one generated Hecate group."""
    hecate_config = _hecate_config(config)
    groups = typ.cast("list[dict[str, object]]", hecate_config["groups"])
    for group in groups:
        if group["name"] == group_name:
            return typ.cast("list[str]", group["allowed"])
    raise AssertionError(group_name)
