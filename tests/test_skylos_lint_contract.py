"""Contract tests for the blocking Skylos dead-code lint gate."""

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
    assert any(dependency.startswith("skylos") for dependency in dependencies)


def test_skylos_configuration_documents_every_exception() -> None:
    """Require reasons for both named and entry-point exceptions."""
    config = _pyproject()
    tool_config = typ.cast("dict[str, object]", config["tool"])

    skylos = typ.cast("dict[str, object]", tool_config["skylos"])
    whitelist = typ.cast("dict[str, object]", skylos["whitelist"])
    documented = typ.cast("dict[str, str]", whitelist["documented"])
    assert documented
    assert all(reason.strip() for reason in documented.values())

    dead_code = typ.cast("dict[str, object]", skylos["dead_code"])
    entrypoints = typ.cast("list[dict[str, object]]", dead_code["entrypoints"])
    assert entrypoints
    assert all(
        isinstance(reason := entrypoint.get("reason"), str) and reason.strip()
        for entrypoint in entrypoints
    )

    gate = typ.cast("dict[str, object]", skylos["gate"])
    assert gate["strict"] is True


def test_make_lint_runs_local_blocking_dead_code_scan() -> None:
    """Keep the Skylos invocation deterministic and non-interactive."""
    makefile = (REPOSITORY_ROOT / "Makefile").read_text(encoding="utf-8")

    expected_command = (
        "$(SKYLOS) $(SKYLOS_TARGETS) --category dead_code --gate "
        "--format concise --no-upload --no-provenance"
    )
    assert expected_command in makefile
    assert "SKYLOS = $(UV_ENV) $(UV) run skylos" in makefile
    assert "SKYLOS_TARGETS ?= $(PYLINT_TARGETS)" in makefile


def test_skylos_allow_requires_name_and_reason() -> None:
    """Guard the only supported command for adding a named exception."""
    makefile = (REPOSITORY_ROOT / "Makefile").read_text(encoding="utf-8")

    assert "skylos-allow: ##" in makefile
    assert 'test -n "$(strip $(NAME))"' in makefile
    assert 'test -n "$(strip $(REASON))"' in makefile
    command = '$(SKYLOS) whitelist "$(NAME)" --reason "$(REASON)"'
    assert makefile.count(command) == 1


def test_skylos_cache_is_ignored() -> None:
    """Keep local grep-verification cache files out of version control."""
    gitignore = (REPOSITORY_ROOT / ".gitignore").read_text(encoding="utf-8")

    assert ".skylos/" in gitignore.splitlines()
