"""Regression tests for production cost group classification."""

import tomllib
import typing as typ
from pathlib import Path

EXPECTED_PRODUCTION_COST_GROUPS = {
    "episodic.cost.engine": "domain_ports",
    "episodic.cost.ports": "domain_ports",
    "episodic.cost.pricing_catalogue": "outbound_adapter",
    "episodic.cost.pricing_catalogue._document": "outbound_adapter",
    "episodic.cost.pricing_catalogue._errors": "outbound_adapter",
    "episodic.cost.pricing_catalogue._yaml_loader": "outbound_adapter",
    "episodic.cost.pricing_catalogue.file_loader": "outbound_adapter",
    "episodic.cost.pricing_snapshot": "domain_ports",
    "episodic.cost.pricing_snapshot_hash": "domain_ports",
    "episodic.cost.pricing_snapshot_ports": "domain_ports",
    "episodic.cost.pricing_snapshot_values": "domain_ports",
    "episodic.cost.primitives": "domain_ports",
    "episodic.cost.recorder": "application",
    "episodic.cost.storage": "outbound_adapter",
    "episodic.cost.storage.adapters": "outbound_adapter",
    "episodic.cost.storage.metering": "outbound_adapter",
    "episodic.cost.storage.models": "outbound_adapter",
    "episodic.cost.storage.pricing_snapshot_store": "outbound_adapter",
}

#: The package facade re-exports ports alongside the application recorder, so
#: no single policy group describes it. ``_time`` depends only on the standard
#: library. Both predate the cost boundary and stay deliberately unclassified;
#: every other module must match an intended group.
UNGROUPED_COST_MODULES = frozenset({"episodic.cost", "episodic.cost._time"})


def test_production_config_classifies_cost_in_strict_order() -> None:
    """Every cost module is classified by a policy group that fits its layer."""
    groups = _production_hecate_groups()
    group_names = [typ.cast("str", group["name"]) for group in groups]
    group_by_name = {typ.cast("str", group["name"]): group for group in groups}

    assert group_names.index("domain_ports") < group_names.index("outbound_adapter"), (
        "domain ports must be classified before the outbound adapter group"
    )
    assert group_by_name["domain_ports"]["allowed"] == [
        "domain_ports",
        "logging_port",
    ], "domain ports must not depend on concrete third-party libraries"
    assert "sqlalchemy" in typ.cast(
        "list[str]", group_by_name["external_libraries"]["prefixes"]
    ), "SQLAlchemy must stay behind the external-library boundary"

    module_groups = _production_cost_module_groups(groups)
    ungrouped = {name for name, group in module_groups.items() if group is None}
    assert ungrouped == UNGROUPED_COST_MODULES, (
        "every cost module outside the facade and its stdlib-only helper "
        "must match a production Hecate group"
    )
    assert {
        name: group for name, group in module_groups.items() if group is not None
    } == EXPECTED_PRODUCTION_COST_GROUPS, (
        "every cost Python module must match its intended production group"
    )


def test_production_cost_v1_modules_keep_their_boundaries() -> None:
    """The content-addressed pricing modules cannot drift across layers."""
    groups = _production_hecate_groups()

    assert (
        _production_hecate_group_for_module("episodic.cost.pricing_snapshot", groups)
        == "domain_ports"
    ), "the pricing snapshot value objects belong to the domain"
    assert (
        _production_hecate_group_for_module(
            "episodic.cost.pricing_snapshot_hash", groups
        )
        == "domain_ports"
    ), "canonical hashing must stay free of adapters and third-party libraries"
    assert (
        _production_hecate_group_for_module(
            "episodic.cost.pricing_catalogue._document", groups
        )
        == "outbound_adapter"
    ), "the v1 catalogue document parser is an outbound adapter concern"
    assert (
        _production_hecate_group_for_module(
            "episodic.cost.pricing_catalogue._yaml_loader", groups
        )
        == "outbound_adapter"
    ), "YAML parsing stays in the catalogue adapter, never in the domain"
    assert (
        _production_hecate_group_for_module(
            "episodic.cost.storage.pricing_snapshot_store", groups
        )
        == "outbound_adapter"
    ), "pricing snapshot persistence belongs to the outbound adapter"

    group_by_name = {typ.cast("str", group["name"]): group for group in groups}
    directory_suffixes = {
        "episodic.cost.pricing_snapshot",
        "episodic.cost.pricing_snapshot_hash",
        "episodic.cost.pricing_snapshot_ports",
    }
    domain_prefixes = set(
        typ.cast("list[str]", group_by_name["domain_ports"]["prefixes"])
    )
    assert directory_suffixes <= domain_prefixes, (
        "content-addressed pricing modules must be named explicitly, because a "
        "broad episodic.cost prefix would let adapters pass the domain policy"
    )


def _production_hecate_groups() -> list[dict[str, object]]:
    """Read Hecate groups from the production pyproject configuration."""
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    config = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    tool_config = typ.cast("dict[str, object]", config["tool"])
    hecate_config = typ.cast("dict[str, object]", tool_config["hecate"])
    return typ.cast("list[dict[str, object]]", hecate_config["groups"])


def _production_cost_module_groups(
    groups: list[dict[str, object]],
) -> dict[str, str | None]:
    """Classify every production cost module by its first matching group."""
    cost_root = Path(__file__).resolve().parents[1] / "episodic" / "cost"
    module_names = [
        _module_name(module_path, cost_root)
        for module_path in sorted(cost_root.rglob("*.py"))
    ]
    assert module_names, f"No Python modules found under cost package {cost_root}"
    return {
        module_name: _production_hecate_group_for_module(module_name, groups)
        for module_name in module_names
    }


def _module_name(module_path: Path, cost_root: Path) -> str:
    """Return the dotted module name for a cost package source file."""
    parts = module_path.relative_to(cost_root).with_suffix("").parts
    package_parts = ["episodic", "cost", *parts]
    if package_parts[-1] == "__init__":
        package_parts.pop()
    return ".".join(package_parts)


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
