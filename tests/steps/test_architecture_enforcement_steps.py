"""BDD steps for architecture-enforcement behaviour."""

from __future__ import annotations

import dataclasses as dc
import subprocess  # noqa: S404  # BDD scenarios validate the public CLI.
import sys
from pathlib import Path

import pytest
from pytest_bdd import given, parsers, scenario, then, when


@dc.dataclass(slots=True)
class ArchitectureContext:
    """State shared by architecture-enforcement BDD steps."""

    package_name: str = ""
    completed_process: subprocess.CompletedProcess[str] | None = None


@pytest.fixture
def context() -> ArchitectureContext:
    """Provide scenario-local architecture-checker state."""
    return ArchitectureContext()


@scenario(
    "../features/architecture_enforcement.feature",
    "A violating domain module is rejected with a clear diagnostic",
)
def test_domain_violation_is_rejected() -> None:
    """Run the domain-violation scenario."""


@scenario(
    "../features/architecture_enforcement.feature",
    "A violating inbound adapter is rejected with a clear diagnostic",
)
def test_inbound_adapter_violation_is_rejected() -> None:
    """Run the inbound-adapter violation scenario."""


@scenario(
    "../features/architecture_enforcement.feature",
    "A composition root that wires adapters is accepted",
)
def test_composition_root_wiring_is_accepted() -> None:
    """Run the composition-root acceptance scenario."""


@given(parsers.parse('the architecture fixture package "{package_name}"'))
def architecture_fixture_package(
    context: ArchitectureContext,
    package_name: str,
) -> None:
    """Select a fixture package for the architecture checker."""
    context.package_name = package_name


@when("the architecture checker runs")
def architecture_checker_runs(context: ArchitectureContext) -> None:
    """Run the architecture checker through its command-line entrypoint."""
    package = f"tests.fixtures.architecture.{context.package_name}"
    package_root = Path("tests/fixtures/architecture") / context.package_name
    context.completed_process = subprocess.run(  # noqa: S603
        [
            sys.executable,
            "-m",
            "episodic.architecture",
            "--package",
            package,
            "--root",
            str(package_root),
            "--fixture-policy",
        ],
        check=False,
        capture_output=True,
        text=True,
    )


@then("the architecture check fails")
def architecture_check_fails(context: ArchitectureContext) -> None:
    """Assert the checker rejected the selected fixture package."""
    completed_process = context.completed_process
    assert completed_process is not None
    assert completed_process.returncode == 1


@then("the architecture check passes")
def architecture_check_passes(context: ArchitectureContext) -> None:
    """Assert the checker accepted the selected fixture package."""
    completed_process = context.completed_process
    assert completed_process is not None
    assert completed_process.returncode == 0
    assert completed_process.stderr == ""


@then(parsers.parse('the architecture diagnostic mentions "{expected_text}"'))
def architecture_diagnostic_mentions(
    context: ArchitectureContext,
    expected_text: str,
) -> None:
    """Assert a stable diagnostic substring was emitted."""
    completed_process = context.completed_process
    assert completed_process is not None
    output = f"{completed_process.stdout}\n{completed_process.stderr}"
    assert expected_text in output
