# ruff: noqa: C901, PLR0911, S101, TC003
"""Run Pylint under PyPy with the local Astroid compatibility patch."""

from __future__ import annotations

import inspect
import sys
import types
import warnings

from astroid import node_classes, nodes, raw_building  # ty: ignore[unresolved-import]
from astroid.raw_building import (  # ty: ignore[unresolved-import]
    IS_PYPY,
    _build_from_function,
    _safe_has_attribute,
    attach_dummy_node,
    build_dummy,
    build_module,
    object_build_class,
    object_build_datadescriptor,
    object_build_methoddescriptor,
)

_IGNORED_GETATTR_ERRORS = (AttributeError, TypeError)
_GET_MEMBER_FAILED = object()
_SKIP = object()


def _get_member(
    obj: types.ModuleType | type,
    alias: str,
) -> tuple[object, bool]:
    """Return a member from ``obj`` with its PyPy descriptor context."""
    pypy__class_getitem__ = IS_PYPY and alias == "__class_getitem__"
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            member = getattr(obj, alias)
    except _IGNORED_GETATTR_ERRORS:
        return _GET_MEMBER_FAILED, pypy__class_getitem__
    if inspect.ismethod(member) and not pypy__class_getitem__:
        member = member.__func__
    return member, pypy__class_getitem__


def _build_builtin_child(
    self: raw_building.InspectBuilder,
    node: nodes.Module | nodes.ClassDef,
    member: object,
    alias: str,
) -> nodes.NodeNG | object:
    """Build a child for builtins unless Astroid treats it as imported."""
    if self.imported_member(node, member, alias):
        return _SKIP
    return object_build_methoddescriptor(node, member)


def _build_class_child(
    self: raw_building.InspectBuilder,
    node: nodes.Module | nodes.ClassDef,
    member: type,
    alias: str,
) -> nodes.ClassDef | object:
    """Build or reuse a class child unless Astroid treats it as imported."""
    if self.imported_member(node, member, alias):
        return _SKIP
    if member in self._done:
        child = self._done[member]
        assert isinstance(child, nodes.ClassDef)
        return child
    child = object_build_class(node, member)
    self.object_build(child, member)
    return child


def _build_const_child(
    node: nodes.Module | nodes.ClassDef,
    member: object,
    alias: str,
) -> nodes.Const | object:
    """Build a const child unless the alias is already a special attribute."""
    if alias in node.special_attributes:
        return _SKIP
    return nodes.const_factory(member)


def _attach_child_node(
    node: nodes.Module | nodes.ClassDef,
    alias: str,
    child: object,
) -> None:
    """Attach *child* to *node* under *alias* unless it is already present."""
    if child not in node.locals.get(alias, ()):
        node.add_local_node(child, alias)


def _dispatch_member_to_child(  # noqa: PLR0913
    self: raw_building.InspectBuilder,
    node: nodes.Module | nodes.ClassDef,
    member: object,
    alias: str,
    *,
    pypy__class_getitem__: bool = False,
) -> nodes.NodeNG | object:
    """Dispatch members to the matching Astroid builder."""
    if pypy__class_getitem__:
        return _build_builtin_child(self, node, member, alias)
    if inspect.isbuiltin(member):
        return _build_builtin_child(self, node, member, alias)
    if inspect.isclass(member):
        return _build_class_child(self, node, member, alias)
    if inspect.ismethoddescriptor(member):
        return object_build_methoddescriptor(node, member)
    if inspect.isdatadescriptor(member):
        return object_build_datadescriptor(node, member)
    if isinstance(member, tuple(node_classes.CONST_CLS)):
        return _build_const_child(node, member, alias)
    if inspect.isroutine(member):
        return _build_from_function(node, member, self._module)
    if _safe_has_attribute(member, "__all__"):
        child = build_module(alias)
        self.object_build(child, member)
        return child
    return build_dummy(member)


def _resolve_member(
    node: nodes.Module | nodes.ClassDef,
    obj: types.ModuleType | type,
    alias: str,
) -> tuple[object, bool, bool]:
    """Resolve *alias* from *obj* and report whether the caller should skip it."""
    pypy__class_getitem__ = IS_PYPY and alias == "__class_getitem__"
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            member = getattr(obj, alias)
    except _IGNORED_GETATTR_ERRORS:
        attach_dummy_node(node, alias)
        return None, pypy__class_getitem__, True
    if inspect.ismethod(member) and not pypy__class_getitem__:
        member = member.__func__
    return member, pypy__class_getitem__, False


def _build_child_for_member(  # noqa: PLR0913, PLR0917
    builder: raw_building.InspectBuilder,
    node: nodes.Module | nodes.ClassDef,
    member: object,
    alias: str,
    pypy__class_getitem__: bool,  # noqa: FBT001
) -> nodes.NodeNG | None:
    """Build an Astroid child for *member* or return None when it should skip."""
    if inspect.isfunction(member):
        return _build_from_function(node, member, builder._module)
    if inspect.isbuiltin(member) or pypy__class_getitem__:
        if builder.imported_member(node, member, alias):
            return None
        return object_build_methoddescriptor(node, member)
    if inspect.isclass(member):
        if builder.imported_member(node, member, alias):
            return None
        if member in builder._done:
            child = builder._done[member]
            assert isinstance(child, nodes.ClassDef)
            return child
        child = object_build_class(node, member)
        builder.object_build(child, member)
        return child
    if inspect.ismethoddescriptor(member):
        return object_build_methoddescriptor(node, member)
    if inspect.isdatadescriptor(member):
        return object_build_datadescriptor(node, member)
    if isinstance(member, tuple(node_classes.CONST_CLS)):
        if alias in node.special_attributes:
            return None
        return nodes.const_factory(member)
    if inspect.isroutine(member):
        return _build_from_function(node, member, builder._module)
    if _safe_has_attribute(member, "__all__"):
        child = build_module(alias)
        builder.object_build(child, member)
        return child
    return build_dummy(member)


def _object_build_without_pypy_descriptor_aliases(
    self: raw_building.InspectBuilder,
    node: nodes.Module | nodes.ClassDef,
    obj: types.ModuleType | type,
) -> None:
    """Build Astroid nodes while ignoring non-string PyPy ``dir()`` entries."""
    if obj in self._done:
        return
    self._done[obj] = node
    for alias in dir(obj):
        if type(alias) is not str:
            continue
        member, pypy__class_getitem__, skip = _resolve_member(node, obj, alias)
        if skip:
            continue
        child = _build_child_for_member(
            self, node, member, alias, pypy__class_getitem__
        )
        if child is not None and child not in node.locals.get(alias, ()):
            node.add_local_node(child, alias)


def main() -> None:
    """Patch Astroid and delegate to Pylint."""
    raw_building.InspectBuilder.object_build = (
        _object_build_without_pypy_descriptor_aliases
    )
    from pylint.lint import Run  # ty: ignore[unresolved-import]

    Run(sys.argv[1:])


if __name__ == "__main__":
    main()
