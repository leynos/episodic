"""TOML templates used by isolated Hecate architecture fixtures."""

COMPOSITION_ROOT_GROUPS: tuple[str, ...] = (
    "application",
    "composition_root",
    "domain",
    "inbound_adapter",
    "orchestration",
    "orchestration_checkpoint",
    "orchestration_nodes",
    "orchestration_tasks",
    "outbound_adapter",
)
DOMAIN_GROUPS: tuple[str, ...] = ("domain",)
APPLICATION_GROUPS: tuple[str, ...] = ("application", "domain")
ORCHESTRATION_CHECKPOINT_GROUPS: tuple[str, ...] = (
    "orchestration_checkpoint",
    "domain",
)
ORCHESTRATION_NODE_GROUPS: tuple[str, ...] = (
    "orchestration_nodes",
    "domain",
    "orchestration_checkpoint",
)
ORCHESTRATION_GROUPS: tuple[str, ...] = (
    "orchestration",
    "application",
    "domain",
    "orchestration_checkpoint",
    "orchestration_nodes",
)
ORCHESTRATION_TASK_GROUPS: tuple[str, ...] = (
    "orchestration_tasks",
    "application",
    "domain",
)
INBOUND_ADAPTER_GROUPS: tuple[str, ...] = (
    "inbound_adapter",
    "application",
    "domain",
)
OUTBOUND_ADAPTER_GROUPS: tuple[str, ...] = (
    "outbound_adapter",
    "application",
    "domain",
)

_DEFAULT_FIXTURE_CONFIG_TEMPLATE = """\
[tool.hecate]
root_packages = ["{package}"]
default_rule_id = "ARCH001"

[[tool.hecate.groups]]
name = "composition_root"
prefixes = ["{package}.runtime"]
allowed = {composition_root_allowed}

[[tool.hecate.groups]]
name = "domain"
prefixes = ["{package}.domain", "{package}.worker.workloads"]
allowed = {domain_allowed}

[[tool.hecate.groups]]
name = "orchestration_checkpoint"
prefixes = [
    "{package}.orchestration._checkpoint_payload",
    "{package}.orchestration._checkpoint_dto",
    "{package}.orchestration._payload_dto",
]
allowed = {orchestration_checkpoint_allowed}

[[tool.hecate.groups]]
name = "orchestration_nodes"
prefixes = ["{package}.orchestration._graph_nodes"]
allowed = {orchestration_node_allowed}

[[tool.hecate.groups]]
name = "orchestration_tasks"
prefixes = ["{package}.worker.tasks"]
allowed = {orchestration_task_allowed}

[[tool.hecate.groups]]
name = "orchestration"
prefixes = ["{package}.orchestration"]
allowed = {orchestration_allowed}

[[tool.hecate.groups]]
name = "application"
prefixes = ["{package}.service"]
allowed = {application_allowed}

[[tool.hecate.groups]]
name = "inbound_adapter"
prefixes = ["{package}.api", "{package}.worker.topology"]
allowed = {inbound_adapter_allowed}

[[tool.hecate.groups]]
name = "outbound_adapter"
prefixes = [{outbound_prefixes}]
allowed = {outbound_adapter_allowed}
"""

_EXTERNAL_LOGGING_FIXTURE_CONFIG_TEMPLATE = """\
[tool.hecate]
root_packages = ["{package}"]
default_rule_id = "ARCH001"
include_external_packages = true

[[tool.hecate.groups]]
name = "logging_port"
prefixes = ["{package}.logging"]
allowed = ["logging_port", "logging_backend"]

[[tool.hecate.groups]]
name = "logging_backend"
prefixes = ["femtologging"]
allowed = ["logging_port"]

[[tool.hecate.groups]]
name = "external_libraries"
prefixes = [
    "alembic",
    "celery",
    "falcon",
    "httpx",
    "langgraph",
    "openai",
    "pydantic",
    "sqlalchemy",
]
allowed = ["external_libraries"]

[[tool.hecate.groups]]
name = "composition_root"
prefixes = ["{package}.runtime"]
allowed = [
    "application",
    "composition_root",
    "domain",
    "external_libraries",
    "inbound_adapter",
    "logging_port",
    "outbound_adapter",
]

[[tool.hecate.groups]]
name = "domain"
prefixes = ["{package}.domain"]
allowed = ["domain", "external_libraries", "logging_port"]

[[tool.hecate.groups]]
name = "application"
prefixes = ["{package}.service"]
allowed = ["application", "domain", "external_libraries", "logging_port"]

[[tool.hecate.groups]]
name = "inbound_adapter"
prefixes = ["{package}.api"]
allowed = [
    "application",
    "domain",
    "external_libraries",
    "inbound_adapter",
    "logging_port",
]

[[tool.hecate.groups]]
name = "outbound_adapter"
prefixes = ["{package}.storage"]
allowed = [
    "application",
    "domain",
    "external_libraries",
    "logging_port",
    "outbound_adapter",
]
"""


def _toml_string_array(values: tuple[str, ...]) -> str:
    """Return a TOML array of quoted strings."""
    return "[" + ", ".join(f'"{value}"' for value in values) + "]"


def render_default_fixture_config(
    package: str,
    *,
    treats_package_barrel_as_outbound: bool,
) -> str:
    """Render the unchanged internal-only fixture policy."""
    package_barrel = f', "{package}"' if treats_package_barrel_as_outbound else ""
    outbound_prefixes = f'"{package}.storage", "{package}.adapter"{package_barrel}'
    return _DEFAULT_FIXTURE_CONFIG_TEMPLATE.format(
        package=package,
        outbound_prefixes=outbound_prefixes,
        composition_root_allowed=_toml_string_array(COMPOSITION_ROOT_GROUPS),
        domain_allowed=_toml_string_array(DOMAIN_GROUPS),
        orchestration_checkpoint_allowed=_toml_string_array(
            ORCHESTRATION_CHECKPOINT_GROUPS,
        ),
        orchestration_node_allowed=_toml_string_array(ORCHESTRATION_NODE_GROUPS),
        orchestration_task_allowed=_toml_string_array(ORCHESTRATION_TASK_GROUPS),
        orchestration_allowed=_toml_string_array(ORCHESTRATION_GROUPS),
        application_allowed=_toml_string_array(APPLICATION_GROUPS),
        inbound_adapter_allowed=_toml_string_array(INBOUND_ADAPTER_GROUPS),
        outbound_adapter_allowed=_toml_string_array(OUTBOUND_ADAPTER_GROUPS),
    )


def render_external_logging_fixture_config(package: str) -> str:
    """Render a fixture policy that rejects backend imports outside logging."""
    return _EXTERNAL_LOGGING_FIXTURE_CONFIG_TEMPLATE.format(package=package)
