"""Unit tests for generated Hecate fixture policies."""

import tomllib
import typing as typ

from architecture_hecate_config import (
    BARREL_OUTBOUND_FIXTURE,
    LOGGING_PORT_FIXTURE,
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

    assert _group_prefixes(config, "outbound_adapter") == [
        f"{package}.storage",
        f"{package}.adapter",
    ], "outbound-adapter prefixes must identify fixture adapter modules"


def test_fixture_config_barrel_fixture_includes_package_barrel(
    tmp_path: Path,
) -> None:
    """The barrel fixture config classifies the package barrel as outbound."""
    package = f"tests.fixtures.architecture.{BARREL_OUTBOUND_FIXTURE}"

    config = _read_fixture_config(tmp_path, BARREL_OUTBOUND_FIXTURE)

    assert _group_prefixes(config, "outbound_adapter") == [
        f"{package}.storage",
        f"{package}.adapter",
        package,
    ], "barrel fixture outbound prefixes must include storage and package roots"


def test_fixture_config_writes_expected_toml_shape(tmp_path: Path) -> None:
    """Generated fixture configs expose Hecate's expected policy shape."""
    package_name = "allowed_case"
    package = f"tests.fixtures.architecture.{package_name}"

    config = _read_fixture_config(tmp_path, package_name)

    _assert_expected_base_groups(config, package)
    _assert_expected_orchestration_groups(config, package)


def _assert_expected_base_groups(
    config: dict[str, object],
    package: str,
) -> None:
    """Assert the generated base Hecate groups."""
    hecate_config = _hecate_config(config)
    assert hecate_config["root_packages"] == [package], (
        "Hecate root_packages must contain the fixture package"
    )
    assert hecate_config["default_rule_id"] == "ARCH001", (
        "Hecate default_rule_id must be ARCH001"
    )
    assert _group_names(config) == [
        "composition_root",
        "domain",
        "orchestration_checkpoint",
        "orchestration_nodes",
        "orchestration_tasks",
        "orchestration",
        "application",
        "inbound_adapter",
        "outbound_adapter",
    ], "Hecate groups must retain first-match policy order"
    assert _group_prefixes(config, "composition_root") == [f"{package}.runtime"], (
        "composition_root must match the runtime module"
    )
    assert _group_allowed(config, "composition_root") == [
        "application",
        "composition_root",
        "domain",
        "inbound_adapter",
        "orchestration",
        "orchestration_checkpoint",
        "orchestration_nodes",
        "orchestration_tasks",
        "outbound_adapter",
    ], "composition_root must allow every configured architecture group"
    assert _group_prefixes(config, "domain") == [
        f"{package}.domain",
        f"{package}.worker.workloads",
    ], "domain must include domain and workload modules"
    assert _group_allowed(config, "domain") == ["domain"], (
        "domain group must allow only domain imports"
    )
    assert _group_allowed(config, "application") == ["application", "domain"], (
        "application must allow application and domain imports"
    )
    assert _group_prefixes(config, "inbound_adapter") == [
        f"{package}.api",
        f"{package}.worker.topology",
    ], "inbound_adapter must match API and worker topology modules"
    assert _group_allowed(config, "inbound_adapter") == [
        "inbound_adapter",
        "application",
        "domain",
    ], "inbound_adapter must allow inbound, application, and domain imports"
    assert _group_allowed(config, "outbound_adapter") == [
        "outbound_adapter",
        "application",
        "domain",
    ], "outbound_adapter must allow outbound, application, and domain imports"


def _assert_expected_orchestration_groups(
    config: dict[str, object],
    package: str,
) -> None:
    """Assert the generated orchestration Hecate groups."""
    assert _group_prefixes(config, "orchestration_checkpoint") == [
        f"{package}.orchestration._checkpoint_payload",
        f"{package}.orchestration._checkpoint_dto",
        f"{package}.orchestration._payload_dto",
    ], "checkpoint group must match checkpoint payload modules"
    assert _group_allowed(config, "orchestration_checkpoint") == [
        "orchestration_checkpoint",
        "domain",
    ], "checkpoint group must allow checkpoint and domain imports"
    assert _group_prefixes(config, "orchestration_nodes") == [
        f"{package}.orchestration._graph_nodes",
    ], "node group must match only the graph node module"
    assert _group_allowed(config, "orchestration_nodes") == [
        "orchestration_nodes",
        "domain",
        "orchestration_checkpoint",
    ], "node group must allow node, domain, and checkpoint imports"
    assert _group_prefixes(config, "orchestration_tasks") == [
        f"{package}.worker.tasks",
    ], "task group must match worker tasks"
    assert _group_allowed(config, "orchestration_tasks") == [
        "orchestration_tasks",
        "application",
        "domain",
    ], "task group must allow task, application, and domain imports"
    assert _group_prefixes(config, "orchestration") == [
        f"{package}.orchestration",
    ], "orchestration group must match the orchestration package"
    assert _group_allowed(config, "orchestration") == [
        "orchestration",
        "application",
        "domain",
        "orchestration_checkpoint",
        "orchestration_nodes",
    ], "orchestration must allow its declared internal dependencies"


def test_external_logging_fixture_config_enforces_the_port_boundary(
    tmp_path: Path,
) -> None:
    """The opt-in fixture policy tracks external imports and isolates femtologging."""
    package = f"tests.fixtures.architecture.{LOGGING_PORT_FIXTURE}"
    config = _read_fixture_config(
        tmp_path,
        LOGGING_PORT_FIXTURE,
        policy_variant="external_logging",
    )

    assert _hecate_config(config)["include_external_packages"] is True, (
        "external logging fixtures must analyse third-party imports"
    )
    assert _group_prefixes(config, "logging_port") == [f"{package}.logging"], (
        "logging port must match before generic fixture groups"
    )
    assert _group_prefixes(config, "logging_backend") == ["femtologging"], (
        "femtologging must have a dedicated backend group"
    )
    assert _group_allowed(config, "logging_backend") == ["logging_port"], (
        "Hecate groups need a non-empty allowed list without widening the port"
    )
    groups = typ.cast("list[dict[str, object]]", _hecate_config(config)["groups"])
    allowed_backend_groups = [
        typ.cast("str", group["name"])
        for group in groups
        if "logging_backend" in typ.cast("list[str]", group["allowed"])
    ]
    assert allowed_backend_groups == ["logging_port"], (
        "only the logging port may import the femtologging backend"
    )
    assert "logging_backend" not in _group_allowed(config, "inbound_adapter"), (
        "inbound adapters must not import the raw logging backend"
    )


def _read_fixture_config(
    tmp_path: Path,
    package_name: str,
    *,
    policy_variant: typ.Literal["default", "external_logging"] = "default",
) -> dict[str, object]:
    """Write and parse the fixture Hecate config."""
    config_path = write_fixture_config(
        tmp_path,
        package_name,
        policy_variant=policy_variant,
    )
    return tomllib.loads(config_path.read_text(encoding="utf-8"))


def _hecate_config(config: dict[str, object]) -> dict[str, object]:
    """Return the generated `[tool.hecate]` config table."""
    tool_config = typ.cast("dict[str, object]", config["tool"])
    return typ.cast("dict[str, object]", tool_config["hecate"])


def _group_prefixes(config: dict[str, object], group_name: str) -> list[str]:
    """Return prefixes for one generated Hecate group."""
    hecate_config = _hecate_config(config)
    groups = typ.cast("list[dict[str, object]]", hecate_config["groups"])
    for group in groups:
        if group["name"] == group_name:
            return typ.cast("list[str]", group["prefixes"])
    raise AssertionError(group_name)


def _group_names(config: dict[str, object]) -> list[str]:
    """Return generated Hecate group names in matching order."""
    hecate_config = _hecate_config(config)
    groups = typ.cast("list[dict[str, object]]", hecate_config["groups"])
    return [typ.cast("str", group["name"]) for group in groups]


def _group_allowed(config: dict[str, object], group_name: str) -> list[str]:
    """Return allowed dependency groups for one generated Hecate group."""
    hecate_config = _hecate_config(config)
    groups = typ.cast("list[dict[str, object]]", hecate_config["groups"])
    for group in groups:
        if group["name"] == group_name:
            return typ.cast("list[str]", group["allowed"])
    raise AssertionError(group_name)
