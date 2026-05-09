"""Package barrel re-export discovery for architecture checks."""

import ast
import dataclasses as dc
import typing as typ

if typ.TYPE_CHECKING:
    from pathlib import Path


@dc.dataclass(frozen=True, slots=True)
class _ReexportScanContext:
    """Bundled package context for re-export index scanning."""

    root: Path
    source_path: Path
    package: str
    module_name: str


def _module_name(root: Path, package: str, source_path: Path) -> str:
    """Derive the dotted module name from a source path."""
    relative = source_path.relative_to(root).with_suffix("")
    parts = tuple(part for part in relative.parts if part != "__init__")
    if not parts:
        return package
    return ".".join((package, *parts))


def _build_reexport_index(root: Path, package: str) -> dict[str, str]:
    """Build a map of re-exported symbols to their origin modules."""
    reexport_index: dict[str, str] = {}
    for source_path in sorted(root.rglob("__init__.py")):
        module_name = _module_name(root, package, source_path)
        tree = ast.parse(
            source_path.read_text(encoding="utf-8"), filename=str(source_path)
        )
        ctx = _ReexportScanContext(
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
    ctx: _ReexportScanContext,
    seen_modules: frozenset[str] | None = None,
) -> dict[str, str]:
    """Return the re-export mapping contributed by a single ``from … import`` node."""
    reexports: dict[str, str] = {}
    for alias in node.names:
        if alias.name == "*":
            for exported_name, origin in _exported_symbols_from_module(
                ctx.root, ctx.package, imported_module, seen_modules
            ).items():
                reexports[f"{ctx.module_name}.{exported_name}"] = origin
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
    return tuple(sorted(_exported_symbols_from_module(root, package, module_name)))


def _exported_symbols_from_module(
    root: Path,
    package: str,
    module_name: str,
    seen_modules: frozenset[str] | None = None,
) -> dict[str, str]:
    """Return exported symbol names mapped to their origin modules."""
    if seen_modules is None:
        seen_modules = frozenset()
    if module_name in seen_modules:
        return {}
    seen_modules |= {module_name}

    source_path = _source_path_for_module(root, package, module_name)
    if source_path is None:
        return {}
    ctx = _ReexportScanContext(
        root=root,
        source_path=source_path,
        package=package,
        module_name=module_name,
    )
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    public_symbols = _fallback_public_symbols_from_tree(tree, ctx, seen_modules)
    explicit_exports = _explicit_all_exports(tree)
    if explicit_exports is not None:
        return {
            exported_name: public_symbols.get(
                exported_name, f"{module_name}.{exported_name}"
            )
            for exported_name in explicit_exports
        }
    return {
        exported_name: origin
        for exported_name, origin in public_symbols.items()
        if not exported_name.startswith("_")
    }


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


def _explicit_all_exports(tree: ast.AST) -> tuple[str, ...] | None:
    """Return literal string exports assigned to ``__all__``."""
    for node in tree.body if isinstance(tree, ast.Module) else ():
        if _is_all_assign(node) or _is_all_ann_assign(node):
            values = _string_sequence_values(node.value)
            if values is not None:
                return values
    return None


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


def _string_sequence_values(node: ast.AST | None) -> tuple[str, ...] | None:
    """Return literal string values from a list or tuple node."""
    if not isinstance(node, ast.List | ast.Tuple):
        return None
    values = tuple(
        element.value
        for element in node.elts
        if isinstance(element, ast.Constant) and isinstance(element.value, str)
    )
    return values if len(values) == len(node.elts) else None


def _fallback_public_symbols_from_tree(
    tree: ast.AST,
    ctx: _ReexportScanContext,
    seen_modules: frozenset[str] | None = None,
) -> dict[str, str]:
    """Return public symbols, expanding module-level star imports."""
    if not isinstance(tree, ast.Module):
        return {}

    public_symbols: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and _has_star_alias(node):
            imported_module = _resolve_import_from(
                node, ctx.source_path, ctx.package, ctx.module_name
            )
            if imported_module is not None:
                public_symbols.update(
                    _exported_symbols_from_module(
                        ctx.root, ctx.package, imported_module, seen_modules
                    )
                )
        public_symbols.update(
            _public_symbols_from_node(
                node, ctx.source_path, ctx.package, ctx.module_name
            )
        )
    return public_symbols


def _public_names_from_tree(tree: ast.AST) -> set[str]:
    """Return public names bound at module top level."""
    if not isinstance(tree, ast.Module):
        return set()
    public_names: set[str] = set()
    for node in tree.body:
        public_names.update(_public_names_from_node(node))
    return public_names


def _public_symbols_from_tree(
    tree: ast.AST, root: Path, package: str, module_name: str
) -> dict[str, str]:
    """Return public symbols bound at module top level."""
    if not isinstance(tree, ast.Module):
        return {}
    public_symbols: dict[str, str] = {}
    source_path = _source_path_for_module(root, package, module_name)
    for node in tree.body:
        public_symbols.update(
            _public_symbols_from_node(node, source_path, package, module_name)
        )
    return public_symbols


def _public_names_from_node(node: ast.stmt) -> set[str]:
    """Return public names bound by one module-level statement."""
    return set(_public_symbols_from_node(node, None, "", ""))


def _public_from_class_or_func(
    node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef,
    module_name: str,
) -> dict[str, str]:
    """Return the public symbol bound by a class or function definition."""
    return {node.name: f"{module_name}.{node.name}"}


def _public_from_assign(node: ast.Assign, module_name: str) -> dict[str, str]:
    """Return public symbols bound by a simple assignment."""
    return {
        target.id: f"{module_name}.{target.id}"
        for target in node.targets
        if isinstance(target, ast.Name) and target.id != "__all__"
    }


def _public_from_annassign(node: ast.AnnAssign, module_name: str) -> dict[str, str]:
    """Return the public symbol bound by an annotated assignment."""
    if isinstance(node.target, ast.Name) and node.target.id != "__all__":
        return {node.target.id: f"{module_name}.{node.target.id}"}
    return {}


def _public_from_import(node: ast.Import) -> dict[str, str]:
    """Return public symbols bound by a bare import."""
    return {
        alias.asname or alias.name.split(".", maxsplit=1)[0]: alias.name
        for alias in node.names
    }


def _public_from_importfrom(
    node: ast.ImportFrom,
    source_path: Path | None,
    package: str,
    module_name: str,
) -> dict[str, str]:
    """Return public symbols bound by an import-from statement."""
    if source_path is None:
        return {}
    imported_module = _resolve_import_from(node, source_path, package, module_name)
    if imported_module is None:
        return {}
    return {
        alias.asname or alias.name: f"{imported_module}.{alias.name}"
        for alias in node.names
        if alias.name != "*"
    }


def _public_symbols_from_node(
    node: ast.stmt,
    source_path: Path | None,
    package: str,
    module_name: str,
) -> dict[str, str]:
    """Return public symbols bound by one module-level statement."""
    if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
        return _public_from_class_or_func(node, module_name)
    if isinstance(node, ast.Assign):
        return _public_from_assign(node, module_name)
    if isinstance(node, ast.AnnAssign):
        return _public_from_annassign(node, module_name)
    if isinstance(node, ast.Import):
        return _public_from_import(node)
    if isinstance(node, ast.ImportFrom):
        return _public_from_importfrom(node, source_path, package, module_name)
    return {}


def _has_star_alias(node: ast.ImportFrom) -> bool:
    """Return whether an import-from node contains a star alias."""
    return any(alias.name == "*" for alias in node.names)


def _collect_reexports_from_tree(
    tree: ast.AST,
    ctx: _ReexportScanContext,
) -> dict[str, str]:
    """Collect re-export mappings from one parsed ``__init__`` tree."""
    reexports: dict[str, str] = {}
    for node in tree.body if isinstance(tree, ast.Module) else ():
        if not isinstance(node, ast.ImportFrom):
            continue
        if (
            imported_module := _resolve_import_from(
                node, ctx.source_path, ctx.package, ctx.module_name
            )
        ) is None:
            continue
        reexports.update(
            _reexports_from_import_node(
                node, imported_module, ctx, frozenset({ctx.module_name})
            )
        )
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
