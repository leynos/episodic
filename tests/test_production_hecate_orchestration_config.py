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
    ], "checkpoint dependencies must remain restricted"
    assert group_by_name["orchestration_nodes"]["allowed"] == [
        "orchestration_nodes",
        "domain_ports",
        "orchestration_checkpoint",
    ], "node dependencies must remain restricted"

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
    ], "worker tasks must not depend on adapters"

    module_groups = _production_orchestration_module_groups(groups)
    assert module_groups == EXPECTED_PRODUCTION_ORCHESTRATION_GROUPS, (
        "every orchestration Python module must match its intended production group"
    )


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
