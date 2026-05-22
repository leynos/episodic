"""Tests for hexagonal architecture enforcement."""

import tomllib
import typing as typ

import pytest
from architecture_hecate_config import (
    BARREL_OUTBOUND_FIXTURE,
    run_hecate_fixture_check,
    run_hecate_production_check,
    write_fixture_config,
)

if typ.TYPE_CHECKING:
    from pathlib import Path


def test_fixture_config_normal_fixture_excludes_package_barrel(
    tmp_path: Path,
) -> None:
    """Normal fixture configs classify only storage as the outbound adapter."""
    package_name = "api_imports_outbound_adapter"
    package = f"tests.fixtures.architecture.{package_name}"

    config = _read_fixture_config(tmp_path, package_name)

    assert _group_prefixes(config, "outbound_adapter") == [f"{package}.storage"]


def test_fixture_config_barrel_fixture_includes_package_barrel(
    tmp_path: Path,
) -> None:
    """The barrel fixture config classifies the package barrel as outbound."""
    package = f"tests.fixtures.architecture.{BARREL_OUTBOUND_FIXTURE}"

    config = _read_fixture_config(tmp_path, BARREL_OUTBOUND_FIXTURE)

    assert _group_prefixes(config, "outbound_adapter") == [
        f"{package}.storage",
        package,
    ]


@pytest.mark.parametrize(
    ("package_name", "expected_message_parts"),
    [
        (
            "domain_imports_storage",
            (
                "ARCH001",
                "tests.fixtures.architecture.domain_imports_storage.domain",
                "tests.fixtures.architecture.domain_imports_storage.storage",
            ),
        ),
        (
            "api_imports_outbound_adapter",
            (
                "ARCH001",
                "tests.fixtures.architecture.api_imports_outbound_adapter.api",
                "tests.fixtures.architecture.api_imports_outbound_adapter.storage",
            ),
        ),
        (
            "api_imports_reexported_outbound_adapter",
            (
                "ARCH001",
                "tests.fixtures.architecture.api_imports_reexported_outbound_adapter.api",
                "tests.fixtures.architecture.api_imports_reexported_outbound_adapter.storage",
            ),
        ),
        (
            "api_imports_star_reexported_outbound_adapter",
            (
                "ARCH001",
                "tests.fixtures.architecture.api_imports_star_reexported_outbound_adapter.api",
                "tests.fixtures.architecture.api_imports_star_reexported_outbound_adapter",
            ),
        ),
        (
            "api_imports_nested_star_reexported_outbound_adapter",
            (
                "ARCH001",
                "tests.fixtures.architecture.api_imports_nested_star_reexported_outbound_adapter.api",
                "tests.fixtures.architecture.api_imports_nested_star_reexported_outbound_adapter.storage",
            ),
        ),
        (
            "api_imports_cyclic_star_reexported_outbound_adapter",
            (
                "ARCH001",
                "tests.fixtures.architecture.api_imports_cyclic_star_reexported_outbound_adapter.api",
                "tests.fixtures.architecture.api_imports_cyclic_star_reexported_outbound_adapter.storage",
            ),
        ),
        (
            "explicit_empty_all",
            (
                "ARCH001",
                "tests.fixtures.architecture.explicit_empty_all.api",
                "tests.fixtures.architecture.explicit_empty_all.storage",
            ),
        ),
    ],
)
def test_checker_reports_fixture_boundary_violations(
    package_name: str,
    expected_message_parts: tuple[str, ...],
    tmp_path: Path,
) -> None:
    """Forbidden fixture imports produce stable architecture diagnostics."""
    config_path = write_fixture_config(tmp_path, package_name)

    completed_process = run_hecate_fixture_check(package_name, config_path)

    rendered = f"{completed_process.stdout}\n{completed_process.stderr}"
    assert completed_process.returncode == 1, rendered
    for expected_message_part in expected_message_parts:
        assert expected_message_part in rendered, (
            f"expected {expected_message_part!r} in {rendered!r}"
        )


def test_checker_accepts_allowed_fixture_graph(tmp_path: Path) -> None:
    """Allowed fixture imports do not produce architecture violations."""
    package_name = "allowed_case"
    config_path = write_fixture_config(tmp_path, package_name)

    completed_process = run_hecate_fixture_check(package_name, config_path)

    rendered = f"{completed_process.stdout}\n{completed_process.stderr}"
    assert completed_process.returncode == 0, rendered


def test_checker_accepts_composition_root_fixture_wiring(tmp_path: Path) -> None:
    """Composition roots can wire concrete inbound and outbound adapters."""
    package_name = "composition_root_allows_wiring"
    config_path = write_fixture_config(tmp_path, package_name)

    completed_process = run_hecate_fixture_check(package_name, config_path)

    rendered = f"{completed_process.stdout}\n{completed_process.stderr}"
    assert completed_process.returncode == 0, rendered


def test_production_checker_accepts_scoped_packages() -> None:
    """The scoped production package graph follows the enforced boundaries."""
    completed_process = run_hecate_production_check()

    rendered = f"{completed_process.stdout}\n{completed_process.stderr}"
    assert completed_process.returncode == 0, rendered


def _read_fixture_config(tmp_path: Path, package_name: str) -> dict[str, object]:
    """Write and parse the fixture Hecate config."""
    config_path = write_fixture_config(tmp_path, package_name)
    return tomllib.loads(config_path.read_text(encoding="utf-8"))


def _group_prefixes(config: dict[str, object], group_name: str) -> list[str]:
    """Return prefixes for one generated Hecate group."""
    tool_config = typ.cast("dict[str, object]", config["tool"])
    hecate_config = typ.cast("dict[str, object]", tool_config["hecate"])
    groups = typ.cast("list[dict[str, object]]", hecate_config["groups"])
    for group in groups:
        if group["name"] == group_name:
            return typ.cast("list[str]", group["prefixes"])
    raise AssertionError(group_name)
