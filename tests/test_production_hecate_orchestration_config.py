"""Regression tests for production orchestration group classification."""

import tomllib
import typing as typ
from pathlib import Path

EXPECTED_PRODUCTION_ORCHESTRATION_GROUPS = {
    "episodic.orchestration": "orchestration",
    "episodic.orchestration._action_result_dto": "orchestration_checkpoint",
    "episodic.orchestration._checkpoint_dto": "orchestration_checkpoint",
    "episodic.orchestration._checkpoint_payload": "orchestration_checkpoint",
    "episodic.orchestration._checkpoint_resume": "orchestration",
    "episodic.orchestration._dto": "orchestration_checkpoint",
    "episodic.orchestration._graph_builder": "orchestration",
    "episodic.orchestration._graph_nodes": "orchestration_nodes",
    "episodic.orchestration._graph_protocols": "orchestration_nodes",
    "episodic.orchestration._graph_state": "orchestration_nodes",
    "episodic.orchestration._guest_bios_executor": "orchestration",
    "episodic.orchestration._payload_dto": "orchestration_checkpoint",
    "episodic.orchestration._planning_orchestrator": "orchestration",
    "episodic.orchestration._protocols": "orchestration",
    "episodic.orchestration._result_dto": "orchestration_checkpoint",
    "episodic.orchestration._routing_executor": "orchestration",
    "episodic.orchestration._show_notes_executor": "orchestration",
    "episodic.orchestration._types": "domain_ports",
    "episodic.orchestration._usage": "orchestration_nodes",
    "episodic.orchestration.checkpoints": "orchestration",
    "episodic.orchestration.generation": "orchestration",
    "episodic.orchestration.langgraph": "orchestration",
    "episodic.orchestration.langgraph_costs": "orchestration",
}


def test_production_config_classifies_orchestration_in_strict_order() -> None:
    """Every orchestration module is classified after strict groups take priority."""
    groups = _production_hecate_groups()
    group_names = [typ.cast("str", group["name"]) for group in groups]
    group_by_name = {typ.cast("str", group["name"]): group for group in groups}

    assert (
        group_names.index("orchestration_checkpoint")
        < group_names.index("orchestration_nodes")
        < group_names.index("orchestration")
    ), "checkpoint and node groups must precede broad orchestration"
    assert group_by_name["orchestration_checkpoint"]["allowed"] == [
        "orchestration_checkpoint",
        "domain_ports",
        "logging_port",
    ], "checkpoint dependencies must remain restricted"
    assert group_by_name["orchestration_nodes"]["allowed"] == [
        "orchestration_nodes",
        "domain_ports",
        "orchestration_checkpoint",
        "logging_port",
    ], "node dependencies must remain restricted"
    assert "external_libraries" not in typ.cast(
        "list[str]", group_by_name["domain_ports"]["allowed"]
    ), "domain ports must not depend on concrete third-party libraries"

    orchestration_group = group_by_name["orchestration"]
    assert orchestration_group["prefixes"] == ["episodic.orchestration"], (
        "broad orchestration group must classify the whole package"
    )
    assert orchestration_group["allowed"] == [
        "orchestration",
        "application",
        "domain_ports",
        "orchestration_checkpoint",
        "orchestration_nodes",
        "external_libraries",
        "logging_port",
    ], "broad orchestration must not permit adapter imports"

    orchestration_tasks_group = group_by_name["orchestration_tasks"]
    assert (
        _production_hecate_group_for_module("episodic.worker.tasks", groups)
        == "orchestration_tasks"
    ), "worker tasks must use their dedicated group"
    assert orchestration_tasks_group["allowed"] == [
        "orchestration_tasks",
        "application",
        "domain_ports",
        "external_workers",
        "logging_port",
    ], "worker tasks must not depend on adapters"
    assert "external_libraries" not in typ.cast(
        "list[str]", orchestration_tasks_group["allowed"]
    ), "worker tasks must not depend on arbitrary third-party libraries"

    module_groups = _production_orchestration_module_groups(groups)
    assert module_groups == EXPECTED_PRODUCTION_ORCHESTRATION_GROUPS, (
        "every orchestration Python module must match its intended production group"
    )


def test_production_logging_backend_is_restricted_to_logging_port() -> None:
    """The production group order must not shadow the femtologging boundary."""
    groups = _production_hecate_groups()
    group_names = [typ.cast("str", group["name"]) for group in groups]
    group_by_name = {typ.cast("str", group["name"]): group for group in groups}

    assert (
        group_names.index("logging_port")
        < group_names.index("logging_backend")
        < group_names.index("logging_internals")
        < group_names.index("external_workers")
        < group_names.index("external_libraries")
    ), "logging groups must precede the broad external-library group"
    assert group_by_name["logging_backend"]["allowed"] == ["logging_port"], (
        "the backend group must have a valid non-empty policy"
    )
    assert group_by_name["logging_internals"]["allowed"] == ["logging_internals"], (
        "private logging types must not import the backend or application layers"
    )
    allowed_backend_groups = [
        typ.cast("str", group["name"])
        for group in groups
        if "logging_backend" in typ.cast("list[str]", group["allowed"])
    ]
    assert allowed_backend_groups == ["logging_port"], (
        "only the logging port may import the femtologging backend"
    )
    assert set(
        typ.cast("list[str]", group_by_name["external_workers"]["prefixes"])
    ) == {
        "celery",
        "kombu",
    }, "worker dependencies must have a specific group before external_libraries"
    assert set(typ.cast("list[str]", group_by_name["external_workers"]["allowed"])) == {
        "composition_root",
        "external_workers",
        "inbound_adapter",
        "orchestration_tasks",
    }, "worker dependencies must be limited to their consuming groups"
    assert not {"celery", "kombu"}.intersection(
        typ.cast("list[str]", group_by_name["external_libraries"]["prefixes"])
    ), "worker dependencies must not fall through to the broad external group"


def _production_hecate_groups() -> list[dict[str, object]]:
    """Read Hecate groups from the production pyproject configuration."""
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    config = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    tool_config = typ.cast("dict[str, object]", config["tool"])
    hecate_config = typ.cast("dict[str, object]", tool_config["hecate"])
    return typ.cast("list[dict[str, object]]", hecate_config["groups"])


def _production_orchestration_module_groups(
    groups: list[dict[str, object]],
) -> dict[str, str | None]:
    """Classify each production orchestration module by first matching group."""
    orchestration_root = (
        Path(__file__).resolve().parents[1] / "episodic" / "orchestration"
    )
    module_names = [
        "episodic.orchestration"
        if module_path.name == "__init__.py"
        else f"episodic.orchestration.{module_path.stem}"
        for module_path in orchestration_root.glob("*.py")
    ]
    assert module_names, (
        f"No Python modules found under orchestration package {orchestration_root}"
    )
    return {
        module_name: _production_hecate_group_for_module(module_name, groups)
        for module_name in module_names
    }


def _production_hecate_group_for_module(
    module_name: str,
    groups: list[dict[str, object]],
) -> str | None:
    """Return the first production Hecate group matching a module name."""
    for group in groups:
        prefixes = typ.cast("list[str]", group["prefixes"])
        if any(
            module_name == prefix or module_name.startswith(f"{prefix}.")
            for prefix in prefixes
        ):
            return typ.cast("str", group["name"])
    return None
