"""Static import checker for hexagonal architecture boundaries."""

import argparse
import ast
import dataclasses as dc
import sys
import typing as typ
from pathlib import Path

if typ.TYPE_CHECKING:
    import collections.abc as cabc


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
            "episodic.canonical.ports",
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


def _inbound_adapter_group() -> ModuleGroup:
    """Return the inbound-adapter ModuleGroup."""
    return ModuleGroup(
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
    )


def _outbound_adapter_group() -> ModuleGroup:
    """Return the outbound-adapter ModuleGroup."""
    return ModuleGroup(
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


@dc.dataclass(frozen=True, slots=True)
class _ModuleContext:
    """Bundled per-module context for violation scanning."""

    source_path: Path
    package: str
    module_name: str
    reexport_index: dict[str, str]


@dc.dataclass(frozen=True, slots=True)
class _ReexportContext:
    """Bundled package context for re-export index scanning."""

    root: Path
    source_path: Path
    package: str
    module_name: str


def _violations_for_module(
    ctx: _ModuleContext,
    importer_group: ModuleGroup,
    active_policy: ArchitecturePolicy,
) -> list[ArchitectureViolation]:
    """Return all boundary violations for one module's imports."""
    violations: list[ArchitectureViolation] = []
    for imported_module in _iter_imported_modules(ctx):
        imported_group = active_policy.group_for(imported_module)
        if imported_group is None:
            continue
        if imported_group.name in importer_group.allowed_groups:
            continue
        violations.append(
            ArchitectureViolation(
                rule_id=active_policy.rule_id,
                importer=ctx.module_name,
                imported=imported_module,
                importer_group=importer_group.name,
                imported_group=imported_group.name,
            )
        )
    return violations


def check_architecture(
    *,
    package_root: Path | str = Path("episodic"),
    package: str = "episodic",
    policy: ArchitecturePolicy | None = None,
) -> ArchitectureCheckResult:
    """Check import directions under one package root."""
    root = Path(package_root)
    active_policy = default_policy() if policy is None else policy
    reexport_index = _build_reexport_index(root, package)
    violations: list[ArchitectureViolation] = []
    for source_path in sorted(root.rglob("*.py")):
        module_name = _module_name(root, package, source_path)
        importer_group = active_policy.group_for(module_name)
        if importer_group is None:
            continue
        ctx = _ModuleContext(
            source_path=source_path,
            package=package,
            module_name=module_name,
            reexport_index=reexport_index,
        )
        violations.extend(_violations_for_module(ctx, importer_group, active_policy))
    return ArchitectureCheckResult(violations=tuple(violations))


def _module_name(root: Path, package: str, source_path: Path) -> str:
    """Derive the dotted module name from a source path."""
    relative = source_path.relative_to(root).with_suffix("")
    parts = tuple(part for part in relative.parts if part != "__init__")
    if not parts:
        return package
    return ".".join((package, *parts))


def _iter_imported_modules(ctx: _ModuleContext) -> cabc.Iterator[str]:
    """Yield every imported module name found in one source file."""
    tree = ast.parse(
        ctx.source_path.read_text(encoding="utf-8"), filename=str(ctx.source_path)
    )
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from _iter_direct_imports(node, ctx.package)
        elif isinstance(node, ast.ImportFrom):
            yield from _iter_from_imports(node, ctx)


def _iter_direct_imports(node: ast.Import, package: str) -> cabc.Iterator[str]:
    """Yield scoped module names from a bare ``import`` statement."""
    for alias in node.names:
        if alias.name == package or alias.name.startswith(f"{package}."):
            yield alias.name


def _iter_from_imports(node: ast.ImportFrom, ctx: _ModuleContext) -> cabc.Iterator[str]:
    """Yield scoped module names from a ``from … import`` statement."""
    imported_module = _resolve_import_from(
        node, ctx.source_path, ctx.package, ctx.module_name
    )
    if imported_module is None:
        return
    yield imported_module
    for alias in node.names:
        if alias.name == "*":
            yield from _iter_star_reexports(imported_module, ctx.reexport_index)
            continue
        imported_symbol = f"{imported_module}.{alias.name}"
        yield imported_symbol
        if resolved_reexport := ctx.reexport_index.get(imported_symbol):
            yield resolved_reexport


def _iter_star_reexports(
    imported_module: str, reexport_index: dict[str, str]
) -> cabc.Iterator[str]:
    """Yield all re-export origins for a star import of one module."""
    prefix = f"{imported_module}."
    for exported_symbol, resolved_reexport in reexport_index.items():
        if exported_symbol.startswith(prefix):
            yield exported_symbol
            yield resolved_reexport


def _build_reexport_index(root: Path, package: str) -> dict[str, str]:
    """Build a map of re-exported symbols to their origin modules."""
    reexport_index: dict[str, str] = {}
    for source_path in sorted(root.rglob("__init__.py")):
        module_name = _module_name(root, package, source_path)
        tree = ast.parse(
            source_path.read_text(encoding="utf-8"), filename=str(source_path)
        )
        ctx = _ReexportContext(
            root=root,
            source_path=source_path,
            package=package,
            module_name=module_name,
        )
        reexport_index.update(_collect_reexports_from_tree(tree, ctx))
    return reexport_index


def _reexports_from_import_node(
    node: ast.ImportFrom,
    imported_module: str,
    ctx: _ReexportContext,
) -> dict[str, str]:
    """Return the re-export mapping contributed by a single ``from … import`` node."""
    reexports: dict[str, str] = {}
    for alias in node.names:
        if alias.name == "*":
            for exported_name in _exported_names_from_module(
                ctx.root, ctx.package, imported_module
            ):
                reexports[f"{ctx.module_name}.{exported_name}"] = (
                    f"{imported_module}.{exported_name}"
                )
            continue
        exported_name = alias.asname or alias.name
        reexports[f"{ctx.module_name}.{exported_name}"] = (
            f"{imported_module}.{alias.name}"
        )
    return reexports


def _exported_names_from_module(
    root: Path, package: str, module_name: str
) -> tuple[str, ...]:
    """Return exported symbol names declared by one module."""
    source_path = _source_path_for_module(root, package, module_name)
    if source_path is None:
        return ()
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    if explicit_exports := _explicit_all_exports(tree):
        return explicit_exports
    return tuple(
        sorted(
            name for name in _public_names_from_tree(tree) if not name.startswith("_")
        )
    )


def _source_path_for_module(root: Path, package: str, module_name: str) -> Path | None:
    """Return the source path for a package-local module."""
    if module_name == package:
        relative_parts: tuple[str, ...] = ()
    elif module_name.startswith(f"{package}."):
        relative_parts = tuple(module_name.removeprefix(f"{package}.").split("."))
    else:
        return None

    module_path = root.joinpath(*relative_parts)
    source_path = module_path.with_suffix(".py")
    if source_path.is_file():
        return source_path
    package_path = module_path / "__init__.py"
    if package_path.is_file():
        return package_path
    return None


def _explicit_all_exports(tree: ast.AST) -> tuple[str, ...]:
    """Return literal string exports assigned to ``__all__``."""
    for node in tree.body if isinstance(tree, ast.Module) else ():
        if _is_all_assign(node):
            return _string_sequence_values(node.value)
        if _is_all_ann_assign(node):
            return _string_sequence_values(node.value)
    return ()


def _is_all_assign(node: ast.stmt) -> typ.TypeIs[ast.Assign]:
    """Return whether a statement assigns to ``__all__``."""
    return isinstance(node, ast.Assign) and any(
        isinstance(target, ast.Name) and target.id == "__all__"
        for target in node.targets
    )


def _is_all_ann_assign(node: ast.stmt) -> typ.TypeIs[ast.AnnAssign]:
    """Return whether a statement annotates and assigns ``__all__``."""
    return isinstance(node, ast.AnnAssign) and _is_all_name(node.target)


def _is_all_name(node: ast.AST) -> typ.TypeIs[ast.Name]:
    """Return whether a node names ``__all__``."""
    return isinstance(node, ast.Name) and node.id == "__all__"


def _string_sequence_values(node: ast.AST | None) -> tuple[str, ...]:
    """Return literal string values from a list or tuple node."""
    if not isinstance(node, ast.List | ast.Tuple):
        return ()
    values = tuple(
        element.value
        for element in node.elts
        if isinstance(element, ast.Constant) and isinstance(element.value, str)
    )
    return values if len(values) == len(node.elts) else ()


def _public_names_from_tree(tree: ast.AST) -> set[str]:
    """Return public names bound at module top level."""
    if not isinstance(tree, ast.Module):
        return set()
    public_names: set[str] = set()
    for node in tree.body:
        public_names.update(_public_names_from_node(node))
    return public_names


def _public_names_from_node(node: ast.stmt) -> set[str]:
    """Return public names bound by one module-level statement."""
    if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
        return {node.name}
    if isinstance(node, ast.Assign):
        return {
            target.id
            for target in node.targets
            if isinstance(target, ast.Name) and target.id != "__all__"
        }
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return {node.target.id} if node.target.id != "__all__" else set()
    if isinstance(node, ast.Import | ast.ImportFrom):
        return {
            alias.asname or alias.name.split(".", maxsplit=1)[0] for alias in node.names
        }
    return set()


def _collect_reexports_from_tree(
    tree: ast.AST,
    ctx: _ReexportContext,
) -> dict[str, str]:
    """Collect re-export mappings from one parsed ``__init__`` tree."""
    reexports: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        if (
            imported_module := _resolve_import_from(
                node, ctx.source_path, ctx.package, ctx.module_name
            )
        ) is None:
            continue
        reexports.update(_reexports_from_import_node(node, imported_module, ctx))
    return reexports


def _resolve_import_from(
    node: ast.ImportFrom,
    source_path: Path,
    package: str,
    module_name: str,
) -> str | None:
    """Resolve an ``ImportFrom`` node to an absolute module name."""
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
    """Compute the base module for a relative import."""
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
