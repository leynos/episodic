# ruff: noqa: C901, PLR0912, S101, TC003
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
        pypy__class_getitem__ = IS_PYPY and alias == "__class_getitem__"
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                member = getattr(obj, alias)
        except _IGNORED_GETATTR_ERRORS:
            attach_dummy_node(node, alias)
            continue
        if inspect.ismethod(member) and not pypy__class_getitem__:
            member = member.__func__
        if inspect.isfunction(member):
            child = _build_from_function(node, member, self._module)
        elif inspect.isbuiltin(member) or pypy__class_getitem__:
            if self.imported_member(node, member, alias):
                continue
            child = object_build_methoddescriptor(node, member)
        elif inspect.isclass(member):
            if self.imported_member(node, member, alias):
                continue
            if member in self._done:
                child = self._done[member]
                assert isinstance(child, nodes.ClassDef)
            else:
                child = object_build_class(node, member)
                self.object_build(child, member)
        elif inspect.ismethoddescriptor(member):
            child = object_build_methoddescriptor(node, member)
        elif inspect.isdatadescriptor(member):
            child = object_build_datadescriptor(node, member)
        elif isinstance(member, tuple(node_classes.CONST_CLS)):
            if alias in node.special_attributes:
                continue
            child = nodes.const_factory(member)
        elif inspect.isroutine(member):
            child = _build_from_function(node, member, self._module)
        elif _safe_has_attribute(member, "__all__"):
            child = build_module(alias)
            self.object_build(child, member)
        else:
            child = build_dummy(member)
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
