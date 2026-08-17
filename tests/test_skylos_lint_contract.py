"""Contract tests for the blocking Skylos dead-code lint gate."""

import os
import shutil
import subprocess  # noqa: S404 - regression test executes make without a shell
import tomllib
import typing as typ
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _pyproject() -> dict[str, object]:
    """Load the repository's Python project configuration."""
    return tomllib.loads(
        (REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )


def test_skylos_is_a_development_dependency() -> None:
    """Install Skylos with the tools needed by contributors and CI."""
    config = _pyproject()
    dependency_groups = typ.cast("dict[str, list[str]]", config["dependency-groups"])

    dependencies = dependency_groups["dev"]
    assert any(dependency.startswith("skylos") for dependency in dependencies), (
        "Expected Skylos in the development dependency group."
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
    makefile = (REPOSITORY_ROOT / "Makefile").read_text(encoding="utf-8")

    expected_command = (
        "$(SKYLOS) $(SKYLOS_PRODUCTION_TARGETS) --category dead_code --gate "
        "--format concise --no-upload --no-provenance --no-grep-verify"
    )
    assert expected_command in makefile, (
        "Expected make lint to run the blocking production-only Skylos command."
    )
    assert (
        "SKYLOS = $(UV_ENV) $(UV) run skylos --config-file pyproject.toml" in makefile
    ), "Expected the local Skylos command to load pyproject.toml."
    production_targets = next(
        line
        for line in makefile.splitlines()
        if line.startswith("SKYLOS_PRODUCTION_TARGETS ?=")
    )
    assert (
        production_targets
        == "SKYLOS_PRODUCTION_TARGETS ?= alembic episodic openai_test_types.py"
    ), "Expected an explicit production-only Skylos target variable."
    assert "SKYLOS_PRODUCTION_TARGETS ?= $(PYLINT_TARGETS)" not in makefile, (
        "Expected the blocking Skylos scan not to reuse Pylint targets."
    )
    assert "tests" not in production_targets, (
        "Expected tests to be excluded from the production Skylos graph."
    )
    assert "--no-grep-verify" in expected_command, (
        "Expected test references to be excluded from production liveness checks."
    )


def test_skylos_allow_requires_name_and_reason() -> None:
    """Guard the command that adds a named, non-entry-point exception."""
    makefile = (REPOSITORY_ROOT / "Makefile").read_text(encoding="utf-8")

    required_fragments = (
        "skylos-allow: ## Document one named Skylos exception, not an entry point",
        "skylos-allow: export SKYLOS_NAME = $(value NAME)",
        "skylos-allow: export SKYLOS_REASON = $(value REASON)",
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


def test_skylos_cache_is_ignored() -> None:
    """Keep local grep-verification cache files out of version control."""
    gitignore = (REPOSITORY_ROOT / ".gitignore").read_text(encoding="utf-8")

    assert ".skylos/" in gitignore.splitlines(), (
        "Expected the local Skylos cache directory to be ignored."
    )
