"""Tests for hexagonal architecture enforcement."""

from __future__ import annotations

import typing as typ

import pytest
from architecture_hecate_config import (
    run_hecate_fixture_check,
    run_hecate_production_check,
    write_fixture_config,
)

if typ.TYPE_CHECKING:
    from pathlib import Path


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
