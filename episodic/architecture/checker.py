"""Static import checker for hexagonal architecture boundaries."""

from __future__ import annotations

import argparse
import ast
import dataclasses as dc
import sys
import typing as typ
from pathlib import Path


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


@dc.dataclass(frozen=True, slots=True)
class ArchitectureViolation:
    """A forbidden import between two classified architecture groups."""

    rule_id: str
    importer: str
    imported: str
    importer_group: str
    imported_group: str

    def render(self) -> str:
        """Render a stable single-line diagnostic."""
        return (
            f"{self.rule_id}: {self.importer} imports forbidden module "
            f"{self.imported} ({self.importer_group} -> {self.imported_group})"
        )


@dc.dataclass(frozen=True, slots=True)
class ArchitectureCheckResult:
    """Result from checking one package tree."""

    violations: tuple[ArchitectureViolation, ...]

    @property
    def ok(self) -> bool:
        """Return True when no architecture violations were found."""
        return not self.violations


def default_policy() -> ArchitecturePolicy:
    """Return the first-scope Episodic architecture policy."""
    all_groups = frozenset({
        "domain_ports",
        "application",
        "inbound_adapter",
        "outbound_adapter",
        "composition_root",
    })
    return ArchitecturePolicy(
        groups=(
            ModuleGroup(
                name="composition_root",
                module_prefixes=(
                    "episodic.api.runtime",
                    "episodic.worker.runtime",
                ),
                allowed_groups=all_groups,
            ),
            ModuleGroup(
                name="domain_ports",
                module_prefixes=(
                    "episodic.canonical.domain",
                    "episodic.canonical.constraints",
                    "episodic.canonical.ingestion",
                    "episodic.canonical.ingestion_ports",
                    "episodic.canonical.ports",
                    "episodic.llm.ports",
                ),
                allowed_groups=frozenset({"domain_ports"}),
            ),
            ModuleGroup(
                name="application",
                module_prefixes=(
                    "episodic.canonical.services",
                    "episodic.canonical.ingestion_service",
                    "episodic.canonical.profile_templates",
                    "episodic.canonical.reference_documents",
                    "episodic.generation",
                ),
                allowed_groups=frozenset({"domain_ports", "application"}),
            ),
            ModuleGroup(
                name="inbound_adapter",
                module_prefixes=(
                    "episodic.api",
                    "episodic.worker.tasks",
                    "episodic.worker.topology",
                ),
                allowed_groups=frozenset({
                    "domain_ports",
                    "application",
                    "inbound_adapter",
                }),
            ),
            ModuleGroup(
                name="outbound_adapter",
                module_prefixes=(
                    "episodic.canonical.adapters",
                    "episodic.canonical.storage",
                    "episodic.llm.openai_adapter",
                    "episodic.llm.openai_client",
                ),
                allowed_groups=frozenset({
                    "domain_ports",
                    "application",
                    "outbound_adapter",
                }),
            ),
        )
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
            ModuleGroup(
                name="composition_root",
                module_prefixes=(f"{package}.runtime",),
                allowed_groups=all_groups,
            ),
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
                allowed_groups=frozenset({
                    "domain",
                    "application",
                    "outbound_adapter",
                }),
            ),
        )
    )


def check_architecture(
    *,
    package_root: Path | str = Path("episodic"),
    package: str = "episodic",
    policy: ArchitecturePolicy | None = None,
) -> ArchitectureCheckResult:
    """Check import directions under one package root."""
    root = Path(package_root)
    active_policy = default_policy() if policy is None else policy
    violations: list[ArchitectureViolation] = []
    for source_path in sorted(root.rglob("*.py")):
        module_name = _module_name(root, package, source_path)
        importer_group = active_policy.group_for(module_name)
        if importer_group is None:
            continue
        for imported_module in _iter_imported_modules(
            source_path, package, module_name
        ):
            imported_group = active_policy.group_for(imported_module)
            if imported_group is None:
                continue
            if imported_group.name in importer_group.allowed_groups:
                continue
            violations.append(
                ArchitectureViolation(
                    rule_id=active_policy.rule_id,
                    importer=module_name,
                    imported=imported_module,
                    importer_group=importer_group.name,
                    imported_group=imported_group.name,
                )
            )
    return ArchitectureCheckResult(violations=tuple(violations))


def _module_name(root: Path, package: str, source_path: Path) -> str:
    relative = source_path.relative_to(root).with_suffix("")
    parts = tuple(part for part in relative.parts if part != "__init__")
    if not parts:
        return package
    return ".".join((package, *parts))


def _iter_imported_modules(
    source_path: Path,
    package: str,
    module_name: str,
) -> typ.Iterator[str]:
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from _iter_direct_imports(node, package)
        elif isinstance(node, ast.ImportFrom):
            yield from _iter_from_imports(node, source_path, package, module_name)


def _iter_direct_imports(node: ast.Import, package: str) -> typ.Iterator[str]:
    for alias in node.names:
        if alias.name == package or alias.name.startswith(f"{package}."):
            yield alias.name


def _iter_from_imports(
    node: ast.ImportFrom,
    source_path: Path,
    package: str,
    module_name: str,
) -> typ.Iterator[str]:
    imported_module = _resolve_import_from(node, source_path, package, module_name)
    if imported_module is None:
        return
    yield imported_module
    for alias in node.names:
        if alias.name != "*":
            yield f"{imported_module}.{alias.name}"


def _resolve_import_from(
    node: ast.ImportFrom,
    source_path: Path,
    package: str,
    module_name: str,
) -> str | None:
    if node.level:
        module_name = _relative_import_base(node, source_path, module_name)
        if node.module:
            module_name = f"{module_name}.{node.module}" if module_name else node.module
    else:
        module_name = node.module or ""

    if module_name == package or module_name.startswith(f"{package}."):
        return module_name
    return None


def _relative_import_base(
    node: ast.ImportFrom, source_path: Path, module_name: str
) -> str:
    parent_parts = module_name.split(".")
    if source_path.name == "__init__.py":
        module_parts = parent_parts
    else:
        module_parts = parent_parts[:-1]
    drop_count = node.level - 1
    if drop_count:
        module_parts = module_parts[:-drop_count]
    return ".".join(module_parts)


def main(argv: list[str] | None = None) -> int:
    """Run the architecture checker from the command line."""
    parser = argparse.ArgumentParser(
        description="Check Episodic hexagonal architecture import boundaries."
    )
    parser.add_argument("--root", default="episodic", help="Package root to scan.")
    parser.add_argument("--package", default="episodic", help="Import package name.")
    parser.add_argument(
        "--fixture-policy",
        action="store_true",
        help="Use the generic fixture policy for architecture BDD fixtures.",
    )
    args = parser.parse_args(argv)

    policy = fixture_policy(args.package) if args.fixture_policy else default_policy()
    result = check_architecture(
        package_root=Path(args.root),
        package=args.package,
        policy=policy,
    )
    for violation in result.violations:
        print(violation.render(), file=sys.stderr)
    return 0 if result.ok else 1
