"""Tests for hexagonal architecture enforcement."""

from __future__ import annotations

from pathlib import Path

import pytest

from episodic.architecture import (
    ArchitecturePolicy,
    ModuleGroup,
    check_architecture,
)

FIXTURE_ROOT = Path("tests/fixtures/architecture")


def _fixture_policy(package_name: str) -> ArchitecturePolicy:
    package = f"tests.fixtures.architecture.{package_name}"
    return ArchitecturePolicy(
        groups=(
            ModuleGroup(
                name="domain",
                module_prefixes=(f"{package}.domain",),
                allowed_groups=frozenset({"domain"}),
            ),
            ModuleGroup(
                name="application",
                module_prefixes=(f"{package}.service",),
                allowed_groups=frozenset({"domain", "application"}),
            ),
            ModuleGroup(
                name="inbound_adapter",
                module_prefixes=(f"{package}.api",),
                allowed_groups=frozenset({
                    "domain",
                    "application",
                    "inbound_adapter",
                }),
            ),
            ModuleGroup(
                name="outbound_adapter",
                module_prefixes=(f"{package}.storage",),
                allowed_groups=frozenset({"domain", "application", "outbound_adapter"}),
            ),
            ModuleGroup(
                name="composition_root",
                module_prefixes=(f"{package}.runtime",),
                allowed_groups=frozenset({
                    "domain",
                    "application",
                    "inbound_adapter",
                    "outbound_adapter",
                    "composition_root",
                }),
            ),
        )
    )


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
    ],
)
def test_checker_reports_fixture_boundary_violations(
    package_name: str,
    expected_message_parts: tuple[str, ...],
) -> None:
    """Forbidden fixture imports produce stable architecture diagnostics."""
    result = check_architecture(
        package_root=FIXTURE_ROOT / package_name,
        package=f"tests.fixtures.architecture.{package_name}",
        policy=_fixture_policy(package_name),
    )

    assert not result.ok
    rendered = "\n".join(violation.render() for violation in result.violations)
    for expected_message_part in expected_message_parts:
        assert expected_message_part in rendered


def test_checker_accepts_allowed_fixture_graph() -> None:
    """Allowed fixture imports do not produce architecture violations."""
    package_name = "allowed_case"

    result = check_architecture(
        package_root=FIXTURE_ROOT / package_name,
        package=f"tests.fixtures.architecture.{package_name}",
        policy=_fixture_policy(package_name),
    )

    assert result.ok


def test_checker_accepts_composition_root_fixture_wiring() -> None:
    """Composition roots can wire concrete inbound and outbound adapters."""
    package_name = "composition_root_allows_wiring"

    result = check_architecture(
        package_root=FIXTURE_ROOT / package_name,
        package=f"tests.fixtures.architecture.{package_name}",
        policy=_fixture_policy(package_name),
    )

    assert result.ok


def test_production_checker_accepts_scoped_packages() -> None:
    """The scoped production package graph follows the enforced boundaries."""
    result = check_architecture()

    rendered = "\n".join(violation.render() for violation in result.violations)
    assert result.ok, rendered
