"""Static import checker for hexagonal architecture boundaries."""

import ast
import dataclasses as dc
import typing as typ
from pathlib import Path

if typ.TYPE_CHECKING:
    import collections.abc as cabc

from . import policy as architecture_policy
from .policy import ArchitecturePolicy, ModuleGroup, default_policy
from .reexports import _build_reexport_index


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


def fixture_policy(package: str) -> ArchitecturePolicy:
    """Return the generic fixture policy used by behavioural tests."""
    return architecture_policy.fixture_policy(package)


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
    from .cli import main as cli_main

    return cli_main(argv)
