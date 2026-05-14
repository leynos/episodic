"""Architecture policies for hexagonal boundary enforcement."""

import dataclasses as dc


@dc.dataclass(frozen=True, slots=True)
class ModuleGroup:
    """One named architecture layer and the groups it may import."""

    name: str
    module_prefixes: tuple[str, ...]
    allowed_groups: frozenset[str]

    def contains(self, module_name: str) -> bool:
        """Return True when a module belongs to this group."""
        return any(
            module_name == prefix or module_name.startswith(f"{prefix}.")
            for prefix in self.module_prefixes
        )


@dc.dataclass(frozen=True, slots=True)
class ArchitecturePolicy:
    """Dependency-direction policy for a package tree."""

    groups: tuple[ModuleGroup, ...]
    rule_id: str = "ARCH001"

    def group_for(self, module_name: str) -> ModuleGroup | None:
        """Return the first matching module group, if the module is scoped."""
        for group in self.groups:
            if group.contains(module_name):
                return group
        return None


_ALL_GROUPS: frozenset[str] = frozenset({
    "domain_ports",
    "application",
    "inbound_adapter",
    "outbound_adapter",
    "composition_root",
})


def _composition_root_group() -> ModuleGroup:
    """Return the composition-root ModuleGroup."""
    return ModuleGroup(
        name="composition_root",
        module_prefixes=(
            "episodic.api.runtime",
            "episodic.worker.runtime",
        ),
        allowed_groups=_ALL_GROUPS,
    )


def _domain_ports_group() -> ModuleGroup:
    """Return the domain-ports ModuleGroup."""
    return ModuleGroup(
        name="domain_ports",
        module_prefixes=(
            "episodic.canonical.domain",
            "episodic.canonical.constraints",
            "episodic.canonical.ingestion",
            "episodic.canonical.ingestion_ports",
            "episodic.canonical.entity_protocols",
            "episodic.canonical.history_protocols",
            "episodic.canonical.ports",
            "episodic.canonical.reference_protocols",
            "episodic.canonical.unit_of_work_protocols",
            "episodic.llm.ports",
        ),
        allowed_groups=frozenset({"domain_ports"}),
    )


def _application_group() -> ModuleGroup:
    """Return the application ModuleGroup."""
    return ModuleGroup(
        name="application",
        module_prefixes=(
            "episodic.canonical.services",
            "episodic.canonical.ingestion_service",
            "episodic.canonical.profile_templates",
            "episodic.canonical.reference_documents",
            "episodic.generation",
        ),
        allowed_groups=frozenset({"domain_ports", "application"}),
    )


def _make_adapter_group(
    name: str,
    module_prefixes: tuple[str, ...],
) -> ModuleGroup:
    """Return an adapter ModuleGroup allowing domain_ports, application, and self."""
    return ModuleGroup(
        name=name,
        module_prefixes=module_prefixes,
        allowed_groups=frozenset({"domain_ports", "application", name}),
    )


def _inbound_adapter_group() -> ModuleGroup:
    """Return the inbound-adapter ModuleGroup."""
    return _make_adapter_group(
        "inbound_adapter",
        (
            "episodic.api",
            "episodic.worker.tasks",
            "episodic.worker.topology",
        ),
    )


def _outbound_adapter_group() -> ModuleGroup:
    """Return the outbound-adapter ModuleGroup."""
    return _make_adapter_group(
        "outbound_adapter",
        (
            "episodic.canonical.adapters",
            "episodic.canonical.storage",
            "episodic.llm.openai_adapter",
            "episodic.llm.openai_client",
        ),
    )


def default_policy() -> ArchitecturePolicy:
    """Return the first-scope Episodic architecture policy."""
    return ArchitecturePolicy(
        groups=(
            _composition_root_group(),
            _domain_ports_group(),
            _application_group(),
            _inbound_adapter_group(),
            _outbound_adapter_group(),
        )
    )


def _make_fixture_group(
    package: str,
    name: str,
    suffix: str,
    allowed_groups: frozenset[str],
) -> ModuleGroup:
    """Return one fixture ModuleGroup for a package suffix."""
    return ModuleGroup(
        name=name,
        module_prefixes=(f"{package}.{suffix}",),
        allowed_groups=allowed_groups,
    )


def fixture_policy(package: str) -> ArchitecturePolicy:
    """Return the generic fixture policy used by behavioural tests."""
    all_groups = frozenset({
        "domain",
        "application",
        "inbound_adapter",
        "outbound_adapter",
        "composition_root",
    })
    return ArchitecturePolicy(
        groups=(
            _make_fixture_group(
                package,
                "composition_root",
                "runtime",
                all_groups,
            ),
            _make_fixture_group(
                package,
                "domain",
                "domain",
                frozenset({"domain"}),
            ),
            _make_fixture_group(
                package,
                "application",
                "service",
                frozenset({"domain", "application"}),
            ),
            _make_fixture_group(
                package,
                "inbound_adapter",
                "api",
                frozenset({
                    "domain",
                    "application",
                    "inbound_adapter",
                }),
            ),
            _make_fixture_group(
                package,
                "outbound_adapter",
                "storage",
                frozenset({
                    "domain",
                    "application",
                    "outbound_adapter",
                }),
            ),
        )
    )
