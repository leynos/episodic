"""BDD orchestration for the Hecate architecture feature scenarios.

The step definitions bridge the human-readable architecture feature file to
the shared Hecate test helpers in `tests/architecture_hecate_config.py`.
Scenarios select one fixture package, generate the corresponding TOML policy,
invoke Hecate through its CLI wrapper, and assert the behavioural outcome. The
lower-level unit tests cover command construction and config shape; this module
keeps the fixture infrastructure connected to the behaviour-driven acceptance
contract.
"""

from __future__ import annotations

import dataclasses as dc
import typing as typ

import pytest
from architecture_hecate_config import run_hecate_fixture_check, write_fixture_config
from pytest_bdd import given, parsers, scenario, then, when

if typ.TYPE_CHECKING:
    import subprocess  # noqa: S404  # Type-only CompletedProcess reference.
    from pathlib import Path


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


@scenario(
    "../features/architecture_enforcement.feature",
    "A clean orchestration fixture passes",
)
def test_clean_orchestration_fixture_is_accepted() -> None:
    """Run the orchestration acceptance scenario."""


@scenario(
    "../features/architecture_enforcement.feature",
    "A LangGraph node importing an adapter is rejected",
)
def test_langgraph_node_adapter_violation_is_rejected() -> None:
    """Run the LangGraph-node violation scenario."""


@scenario(
    "../features/architecture_enforcement.feature",
    "A Celery task importing an adapter is rejected",
)
def test_celery_task_adapter_violation_is_rejected() -> None:
    """Run the Celery-task violation scenario."""


@scenario(
    "../features/architecture_enforcement.feature",
    "A checkpoint payload importing storage is rejected",
)
def test_checkpoint_payload_storage_violation_is_rejected() -> None:
    """Run the checkpoint-payload violation scenario."""


@given(parsers.parse('the architecture fixture package "{package_name}"'))
def architecture_fixture_package(
    context: ArchitectureContext,
    package_name: str,
) -> None:
    """Select a fixture package for the architecture checker."""
    context.package_name = package_name


@when("the architecture checker runs")
def architecture_checker_runs(context: ArchitectureContext, tmp_path: Path) -> None:
    """Run the architecture checker through its command-line entrypoint."""
    config_path = write_fixture_config(tmp_path, context.package_name)
    context.completed_process = run_hecate_fixture_check(
        context.package_name,
        config_path,
    )


@then("the architecture check fails")
def architecture_check_fails(context: ArchitectureContext) -> None:
    """Assert the checker rejected the selected fixture package."""
    completed_process = context.completed_process
    assert completed_process is not None, "checker did not run"
    assert completed_process.returncode == 1, (
        f"expected exit 1, got {completed_process.returncode}"
    )


@then("the architecture check passes")
def architecture_check_passes(context: ArchitectureContext) -> None:
    """Assert the checker accepted the selected fixture package."""
    completed_process = context.completed_process
    assert completed_process is not None, "checker did not run"
    assert not completed_process.returncode, (
        f"expected exit 0, got {completed_process.returncode}"
    )


@then(parsers.parse('the architecture diagnostic mentions "{expected_text}"'))
def architecture_diagnostic_mentions(
    context: ArchitectureContext,
    expected_text: str,
) -> None:
    """Assert a stable diagnostic substring was emitted."""
    completed_process = context.completed_process
    assert completed_process is not None, "checker did not run"
    output = f"{completed_process.stdout}\n{completed_process.stderr}"
    assert expected_text in output, f"expected {expected_text!r} in {output!r}"
