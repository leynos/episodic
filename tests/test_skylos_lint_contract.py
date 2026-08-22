"""Contract tests for the blocking Skylos dead-code lint gate."""

import os
import shutil
import subprocess  # noqa: S404 - regression test executes make without a shell
import tomllib
import typing as typ
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _pyproject() -> dict[str, object]:
    """Load the repository's Python project configuration."""
    return tomllib.loads(
        (REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )


def test_skylos_is_a_pinned_external_tool() -> None:
    """Keep Skylos out of the project environment and pin its tool release."""
    config = _pyproject()
    dependency_groups = typ.cast("dict[str, list[str]]", config["dependency-groups"])

    dependencies = dependency_groups["dev"]
    assert not any(dependency.startswith("skylos") for dependency in dependencies), (
        "Expected Skylos to be separately provisioned from the development "
        "dependency group."
    )
    makefile = (REPOSITORY_ROOT / "Makefile").read_text(encoding="utf-8")
    assert "SKYLOS_VERSION = 4.33.2" in makefile, (
        "Expected the separately provisioned Skylos tool version to be exact."
    )
    assert "--from 'skylos==$(SKYLOS_VERSION)' skylos" in makefile, (
        "Expected Skylos to run from its separately provisioned tool environment."
    )


def test_skylos_configuration_documents_every_exception() -> None:
    """Require reasons for both named and entry-point exceptions."""
    config = _pyproject()
    tool_config = typ.cast("dict[str, object]", config["tool"])

    skylos = typ.cast("dict[str, object]", tool_config["skylos"])
    whitelist = typ.cast("dict[str, object]", skylos["whitelist"])
    documented = typ.cast("dict[str, str]", whitelist["documented"])
    assert documented, "Expected at least one documented Skylos whitelist entry."
    assert all(reason.strip() for reason in documented.values()), (
        "Expected every documented Skylos whitelist entry to have a reason."
    )

    dead_code = typ.cast("dict[str, object]", skylos["dead_code"])
    entrypoints = typ.cast("list[dict[str, object]]", dead_code["entrypoints"])
    assert entrypoints, "Expected at least one Skylos dead-code entry-point rule."
    assert all(
        isinstance(reason := entrypoint.get("reason"), str) and reason.strip()
        for entrypoint in entrypoints
    ), "Expected every Skylos dead-code entry point to have a reason."

    gate = typ.cast("dict[str, object]", skylos["gate"])
    assert gate["strict"] is True, "Expected the Skylos gate to run in strict mode."


def test_skylos_entrypoint_rules_distinguish_methods_from_functions() -> None:
    """Keep framework methods from being configured as module functions."""
    config = _pyproject()
    tool_config = typ.cast("dict[str, object]", config["tool"])
    skylos = typ.cast("dict[str, object]", tool_config["skylos"])
    dead_code = typ.cast("dict[str, object]", skylos["dead_code"])
    entrypoints = typ.cast("list[dict[str, object]]", dead_code["entrypoints"])
    entrypoint_types = {
        full_name: entrypoint["type"]
        for entrypoint in entrypoints
        for full_name in typ.cast("list[str]", entrypoint["full_name"])
    }

    assert (
        entrypoint_types["episodic.api.app._ShutdownHooksMiddleware.process_shutdown"]
        == "method"
    ), "Expected the Falcon shutdown hook to be classified as a method."
    assert (
        entrypoint_types["episodic.canonical.domain.Checkpoint._validate_options"]
        == "method"
    ), "Expected the checkpoint validator to be classified as a method."
    assert (
        entrypoint_types["episodic.observability.NoopMetrics.increment_counter"]
        == "method"
    ), "Expected the metrics protocol implementation to be classified as a method."


def test_make_lint_runs_local_blocking_dead_code_scan() -> None:
    """Keep the Skylos invocation deterministic and non-interactive."""
    make_executable = shutil.which("make")
    assert make_executable is not None, "Expected make to be available for the test."

    result = subprocess.run(  # noqa: S603 - test executes make without a shell
        [make_executable, "--no-print-directory", "--dry-run", "lint"],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, "Expected make lint dry run to succeed."
    skylos_commands = [
        line
        for line in result.stdout.splitlines()
        if "skylos --config-file pyproject.toml" in line
    ]
    assert len(skylos_commands) == 1, (
        "Expected make lint to expand exactly one blocking Skylos command."
    )
    skylos_command = skylos_commands[0]
    assert "alembic episodic openai_test_types.py" in skylos_command, (
        "Expected the blocking Skylos command to use production-only targets."
    )
    assert " tests" not in skylos_command, (
        "Expected tests to be excluded from the production Skylos graph."
    )
    assert (
        "--category dead_code --gate --format concise --no-upload "
        "--no-provenance --no-grep-verify" in skylos_command
    ), "Expected the blocking Skylos command to retain its gate flags."


def test_skylos_allow_requires_name_and_reason() -> None:
    """Guard the command that adds a named, non-entry-point exception."""
    makefile = (REPOSITORY_ROOT / "Makefile").read_text(encoding="utf-8")

    required_fragments = (
        "skylos-allow: ## Document one named Skylos exception, not an entry point",
        "skylos-allow: export SKYLOS_NAME = $(call cli_value,NAME)",
        "skylos-allow: export SKYLOS_REASON = $(call cli_value,REASON)",
        'test -n "$${SKYLOS_NAME}"',
        'test -n "$${SKYLOS_REASON}"',
        "NAME is required for a named whitelist exception",
        "REASON is required for a named whitelist exception",
    )
    missing_fragments = tuple(
        fragment for fragment in required_fragments if fragment not in makefile
    )
    assert not missing_fragments, (
        f"Expected skylos-allow target requirements; missing {missing_fragments!r}."
    )
    command = '$(SKYLOS) whitelist "$${SKYLOS_NAME}" --reason "$${SKYLOS_REASON}"'
    assert makefile.count(command) == 1, (
        "Expected exactly one safely quoted Skylos whitelist command."
    )


def test_skylos_allow_preserves_metacharacters_as_arguments(tmp_path: Path) -> None:
    """Keep untrusted allow-list values within their original arguments."""
    recorder = tmp_path / "skylos-recorder"
    capture = tmp_path / "arguments.txt"
    marker = tmp_path / "injected-command"
    recorder.write_text(
        '#!/bin/sh\nprintf \'%s\\n\' "$@" > "$SKYLOS_CAPTURE"\n',
        encoding="utf-8",
    )
    recorder.chmod(0o755)
    name = f'registered"; touch {marker}; printf "'
    reason = f"loaded by `touch {marker}` and $(touch {marker})"
    make_executable = shutil.which("make")
    assert make_executable is not None, "Expected make to be available for the test."

    result = subprocess.run(  # noqa: S603 - arguments exercise shell injection safely
        [
            make_executable,
            "--no-print-directory",
            "skylos-allow",
            f"NAME={name}",
            f"REASON={reason}",
            f"SKYLOS={recorder}",
        ],
        cwd=REPOSITORY_ROOT,
        env={**os.environ, "SKYLOS_CAPTURE": str(capture)},
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, "Expected quoted metacharacters to reach Skylos."
    assert capture.read_text(encoding="utf-8").splitlines() == [
        "whitelist",
        name,
        "--reason",
        reason,
    ], "Expected NAME and REASON to remain single whitelist arguments."
    assert not marker.exists(), "Expected no injected shell command to execute."


@pytest.mark.parametrize(
    ("provided_assignment", "expected_error"),
    [
        (
            "REASON=loaded by the verified plugin registry",
            "Error: NAME is required for a named whitelist exception",
        ),
        (
            "NAME=registered_handler",
            "Error: REASON is required for a named whitelist exception",
        ),
    ],
)
def test_skylos_allow_rejects_missing_required_value(
    tmp_path: Path,
    provided_assignment: str,
    expected_error: str,
) -> None:
    """Reject a missing allow-list value before invoking Skylos."""
    recorder = tmp_path / "skylos-recorder"
    capture = tmp_path / "arguments.txt"
    recorder.write_text(
        '#!/bin/sh\nprintf \'%s\\n\' "$@" > "$SKYLOS_CAPTURE"\n',
        encoding="utf-8",
    )
    recorder.chmod(0o755)
    make_executable = shutil.which("make")
    assert make_executable is not None, "Expected make to be available for the test."

    result = subprocess.run(  # noqa: S603 - tests Makefile validation safely
        [
            make_executable,
            "--no-print-directory",
            "skylos-allow",
            provided_assignment,
            f"SKYLOS={recorder}",
        ],
        cwd=REPOSITORY_ROOT,
        env={**os.environ, "SKYLOS_CAPTURE": str(capture)},
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2, "Expected missing values to return status 2."
    assert expected_error in result.stderr, "Expected the missing-value diagnostic."
    assert not capture.exists(), "Expected Skylos not to run after validation fails."


def test_skylos_cache_is_ignored() -> None:
    """Keep local grep-verification cache files out of version control."""
    gitignore = (REPOSITORY_ROOT / ".gitignore").read_text(encoding="utf-8")

    assert ".skylos/" in gitignore.splitlines(), (
        "Expected the local Skylos cache directory to be ignored."
    )
