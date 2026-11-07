"""Regression tests for the Hecate-backed architecture boundary.

These tests exercise the repository's architecture policy through the same
Hecate command-line interface used by `make lint`, while keeping fixture
packages isolated with generated TOML configs. The module owns focused unit
diagnostic contract that connects Hecate output to the behaviour-driven tests
in `tests/steps/test_architecture_enforcement_steps.py`; helper-level unit
coverage lives in `tests/test_architecture_hecate_config.py`.
"""

import json
import tomllib
import typing as typ
from pathlib import Path

import pytest
from architecture_hecate_config import (
    LOGGING_PORT_FIXTURE,
    has_violation,
    run_hecate_fixture_check,
    run_hecate_production_check,
    write_fixture_config,
)

if typ.TYPE_CHECKING:
    import subprocess  # Type-only CompletedProcess reference.

    from syrupy.assertion import SnapshotAssertion


def _fixture_module(package_name: str, module_name: str) -> str:
    """Return a fully qualified architecture fixture module name."""
    return f"tests.fixtures.architecture.{package_name}.{module_name}"


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
        (
            "orchestration_node_imports_outbound_adapter",
            (
                "ARCH001",
                _fixture_module(
                    "orchestration_node_imports_outbound_adapter",
                    "orchestration._graph_nodes",
                ),
                _fixture_module(
                    "orchestration_node_imports_outbound_adapter",
                    "storage",
                ),
            ),
        ),
        (
            "orchestration_node_imports_application_service",
            (
                "ARCH001",
                _fixture_module(
                    "orchestration_node_imports_application_service",
                    "orchestration._graph_nodes",
                ),
                _fixture_module(
                    "orchestration_node_imports_application_service",
                    "service",
                ),
            ),
        ),
        (
            "orchestration_planning_imports_adapter",
            (
                "ARCH001",
                _fixture_module(
                    "orchestration_planning_imports_adapter",
                    "orchestration._planning_orchestrator",
                ),
                _fixture_module("orchestration_planning_imports_adapter", "adapter"),
            ),
        ),
        (
            "orchestration_imports_inbound_adapter",
            (
                "ARCH001",
                _fixture_module(
                    "orchestration_imports_inbound_adapter",
                    "orchestration.generation",
                ),
                _fixture_module("orchestration_imports_inbound_adapter", "api"),
            ),
        ),
        (
            "celery_task_imports_inbound_adapter",
            (
                "ARCH001",
                _fixture_module(
                    "celery_task_imports_inbound_adapter",
                    "worker.tasks",
                ),
                _fixture_module("celery_task_imports_inbound_adapter", "api"),
            ),
        ),
        (
            "celery_task_imports_outbound_adapter",
            (
                "ARCH001",
                _fixture_module(
                    "celery_task_imports_outbound_adapter",
                    "worker.tasks",
                ),
                _fixture_module("celery_task_imports_outbound_adapter", "storage"),
            ),
        ),
        (
            "checkpoint_payload_imports_storage",
            (
                "ARCH001",
                _fixture_module(
                    "checkpoint_payload_imports_storage",
                    "orchestration._checkpoint_payload",
                ),
                _fixture_module("checkpoint_payload_imports_storage", "storage"),
            ),
        ),
        (
            "checkpoint_payload_imports_application",
            (
                "ARCH001",
                _fixture_module(
                    "checkpoint_payload_imports_application",
                    "orchestration._checkpoint_payload",
                ),
                _fixture_module("checkpoint_payload_imports_application", "service"),
            ),
        ),
        (
            "ungrouped_adapter_is_caught",
            (
                "ARCH001",
                _fixture_module(
                    "ungrouped_adapter_is_caught",
                    "orchestration.generation",
                ),
                _fixture_module("ungrouped_adapter_is_caught", "adapter"),
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


def test_checker_rejects_femtologging_outside_logging_port(
    tmp_path: Path,
) -> None:
    """The boundary reports the exact forbidden backend import structurally."""
    config_path = write_fixture_config(tmp_path, LOGGING_PORT_FIXTURE)

    completed_process = run_hecate_fixture_check(
        LOGGING_PORT_FIXTURE,
        config_path,
        output_format="json",
    )

    rendered = _render_process(completed_process)
    assert completed_process.returncode == 1, rendered
    expected_importer = _fixture_module(LOGGING_PORT_FIXTURE, "api")
    assert has_violation(
        completed_process.stdout,
        rule_id="ARCH001",
        importer=expected_importer,
        imported="femtologging",
    ), f"expected ARCH001 for {expected_importer} importing femtologging in {rendered}"


def test_checker_diagnostic_output_matches_snapshot(
    tmp_path: Path,
    snapshot: SnapshotAssertion,
) -> None:
    """One full Hecate diagnostic is snapshotted for format regressions."""
    package_name = "domain_imports_storage"
    config_path = write_fixture_config(tmp_path, package_name)

    completed_process = run_hecate_fixture_check(package_name, config_path)

    assert completed_process.returncode == 1, _render_process(completed_process)
    assert _render_process(completed_process) == snapshot, (
        "rendered Hecate diagnostics must match the recorded snapshot"
    )


def test_orchestration_json_diagnostics_match_snapshot(
    tmp_path: Path,
    snapshot: SnapshotAssertion,
) -> None:
    """Orchestration boundary JSON diagnostics keep a stable shape."""
    package_names = (
        "orchestration_node_imports_outbound_adapter",
        "celery_task_imports_inbound_adapter",
        "checkpoint_payload_imports_storage",
    )
    reports: dict[str, object] = {}
    for package_name in package_names:
        config_path = write_fixture_config(tmp_path, package_name)
        completed_process = run_hecate_fixture_check(
            package_name,
            config_path,
            output_format="json",
        )
        assert completed_process.returncode == 1, _render_process(completed_process)
        reports[package_name] = _normalise_hecate_json_report(completed_process)

    assert reports == snapshot, "normalized JSON diagnostics must match the snapshot"


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


@pytest.mark.parametrize(
    "package_name",
    [
        "orchestration_node_imports_port",
        "orchestration_imports_domain_service",
        "celery_task_imports_domain_service",
    ],
)
def test_checker_accepts_orchestration_fixture_graphs(
    package_name: str,
    tmp_path: Path,
) -> None:
    """Allowed orchestration fixture imports do not produce violations."""
    config_path = write_fixture_config(tmp_path, package_name)

    completed_process = run_hecate_fixture_check(package_name, config_path)

    rendered = f"{completed_process.stdout}\n{completed_process.stderr}"
    assert completed_process.returncode == 0, rendered


def test_production_checker_accepts_scoped_packages() -> None:
    """The scoped production package graph follows the enforced boundaries."""
    completed_process = run_hecate_production_check()

    rendered = f"{completed_process.stdout}\n{completed_process.stderr}"
    assert completed_process.returncode == 0, rendered


def _hecate_group_prefixes() -> list[tuple[str, str]]:
    """Return `(group, prefix)` pairs in declaration order from pyproject.toml."""
    pyproject = tomllib.loads(
        (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(
            encoding="utf-8"
        )
    )
    return [
        (group["name"], prefix)
        for group in pyproject["tool"]["hecate"]["groups"]
        for prefix in group["prefixes"]
    ]


def _prefixes_overlap(ancestor: str, descendant: str) -> bool:
    """Return whether *ancestor* and *descendant* name overlapping prefixes."""
    return descendant == ancestor or descendant.startswith(f"{ancestor}.")


def test_no_prefix_shadows_a_later_group() -> None:
    """An earlier Hecate group must not silently claim a later group's module.

    Hecate classifies a module by the first group whose prefix contains it, so
    an ancestor prefix declared earlier — for example `episodic.llm` in
    `domain_ports` — reclassifies every module of a later group while the gate
    still exits 0. An identical prefix repeated in two groups loses the later
    boundary the same way. This guard makes both silent losses a test failure
    instead.
    """
    pairs = _hecate_group_prefixes()

    shadowing = [
        (earlier_group, earlier_prefix, later_group, later_prefix)
        for earlier_index, (earlier_group, earlier_prefix) in enumerate(pairs)
        for later_group, later_prefix in pairs[earlier_index + 1 :]
        if earlier_group != later_group
        and _prefixes_overlap(earlier_prefix, later_prefix)
    ]

    assert not shadowing, (
        "an earlier Hecate group prefix overlaps a later group's prefix, so "
        "Hecate will classify those modules into the earlier group:\n"
        + "\n".join(
            f"  {earlier_group}:{earlier_prefix} shadows {later_group}:{later_prefix}"
            for earlier_group, earlier_prefix, later_group, later_prefix in shadowing
        )
    )


def _render_process(completed_process: subprocess.CompletedProcess[str]) -> str:
    """Return captured Hecate output in assertion form."""
    return f"stdout:\n{completed_process.stdout}\nstderr:\n{completed_process.stderr}"


def _normalise_hecate_json_report(
    completed_process: subprocess.CompletedProcess[str],
) -> object:
    """Return Hecate JSON output with workspace-specific paths normalised."""
    report = json.loads(completed_process.stdout)
    for violation in report["violations"]:
        violation["source_path"] = str(
            Path(violation["source_path"]).relative_to(Path(__file__).parents[1])
        )
    return report
