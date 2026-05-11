# ruff: noqa: PLR0911, PLR0913, S101, TC003
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


def _dispatch_member_to_child(
    self: raw_building.InspectBuilder,
    node: nodes.Module | nodes.ClassDef,
    member: object,
    alias: str,
) -> nodes.NodeNG | object:
    """Dispatch non-PyPy-special members to the matching Astroid builder."""
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


def _build_child_node(
    self: raw_building.InspectBuilder,
    node: nodes.Module | nodes.ClassDef,
    member: object,
    alias: str,
    *,
    pypy__class_getitem__: bool,
) -> nodes.NodeNG | object:
    """Dispatch member conversion to the matching Astroid child builder."""
    if pypy__class_getitem__:
        return _build_builtin_child(self, node, member, alias)
    return _dispatch_member_to_child(self, node, member, alias)


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
        member, pypy__class_getitem__ = _get_member(obj, alias)
        if member is _GET_MEMBER_FAILED:
            attach_dummy_node(node, alias)
            continue
        child = _build_child_node(
            self,
            node,
            member,
            alias,
            pypy__class_getitem__=pypy__class_getitem__,
        )
        if child is _SKIP:
            continue
        if child not in node.locals.get(alias, ()):
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
