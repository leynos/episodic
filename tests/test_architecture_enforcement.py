"""Tests for hexagonal architecture enforcement."""

from pathlib import Path

import pytest

from episodic.architecture import (
    check_architecture,
)
from episodic.architecture.checker import fixture_policy

FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "architecture"


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
                "tests.fixtures.architecture.api_imports_star_reexported_outbound_adapter.storage",
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
) -> None:
    """Forbidden fixture imports produce stable architecture diagnostics."""
    package = f"tests.fixtures.architecture.{package_name}"

    result = check_architecture(
        package_root=FIXTURE_ROOT / package_name,
        package=package,
        policy=fixture_policy(package),
    )

    rendered = "\n".join(violation.render() for violation in result.violations)
    assert not result.ok, rendered
    for expected_message_part in expected_message_parts:
        assert expected_message_part in rendered, (
            f"expected {expected_message_part!r} in {rendered!r}"
        )


def test_checker_accepts_allowed_fixture_graph() -> None:
    """Allowed fixture imports do not produce architecture violations."""
    package_name = "allowed_case"
    package = f"tests.fixtures.architecture.{package_name}"

    result = check_architecture(
        package_root=FIXTURE_ROOT / package_name,
        package=package,
        policy=fixture_policy(package),
    )

    rendered = "\n".join(violation.render() for violation in result.violations)
    assert result.ok, rendered


def test_checker_accepts_composition_root_fixture_wiring() -> None:
    """Composition roots can wire concrete inbound and outbound adapters."""
    package_name = "composition_root_allows_wiring"
    package = f"tests.fixtures.architecture.{package_name}"

    result = check_architecture(
        package_root=FIXTURE_ROOT / package_name,
        package=package,
        policy=fixture_policy(package),
    )

    rendered = "\n".join(violation.render() for violation in result.violations)
    assert result.ok, rendered


def test_production_checker_accepts_scoped_packages() -> None:
    """The scoped production package graph follows the enforced boundaries."""
    result = check_architecture()

    rendered = "\n".join(violation.render() for violation in result.violations)
    assert result.ok, rendered
