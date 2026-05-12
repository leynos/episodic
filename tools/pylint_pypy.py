"""PyPy-backed Pylint wrapper with Astroid member-resolution patch.

Invocation
----------
The ``lint`` target in the project Makefile executes this module via::

    uv tool run --python pypy --from 'pylint==4.*' python tools/pylint_pypy.py <targets>

The ``--python pypy`` flag selects the UV-managed PyPy runtime, which
surfaces the descriptor-aliasing behaviour that the patch addresses.

Astroid / PyPy compatibility
----------------------------
Astroid's ``InspectBuilder.object_build`` iterates ``dir(obj)`` and calls
``getattr`` for each alias. Under PyPy, some entries returned by ``dir()``
are non-string objects and some ``getattr`` calls raise ``TypeError`` instead
of ``AttributeError``. ``_object_build_without_pypy_descriptor_aliases``
replaces the built-in implementation to handle both cases gracefully.

Member resolution is split across focused helpers:

* ``_resolve_member`` - resolves an alias, unwraps bound methods, and
  signals when the alias must be skipped; the caller is responsible for
  attaching a dummy node on skip.
* ``_dispatch_member_to_child`` - maps a resolved member to the correct
  Astroid builder (builtin, class, descriptor, constant, routine, or module).
* ``_build_builtin_child``, ``_build_class_child``, ``_build_const_child`` -
  type-specific builders that return the ``_SKIP`` sentinel when Astroid
  would treat the member as an imported alias.
* ``_attach_child_node`` - attaches a child to its parent node only when
  the alias is not already present in ``node.locals``.

Pylint message selection
------------------------
Messages are controlled by ``[tool.pylint."messages control"]`` in
``pyproject.toml``, which disables all messages and re-enables a curated
allow-list. ``syntax-error`` is excluded because the managed PyPy runtime
targets Python 3.11 syntax whilst the project targets Python 3.14. The
wrapper catches parse failures from Pylint, reports skipped files, and keeps
parse incompatibilities visible without hiding diagnostics from files PyPy can
analyse.
"""

import inspect
import sys
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
_SKIP = object()


def _cached_child_type_error(member: object, child: object) -> str:
    """Describe a cached Astroid child type invariant failure."""
    return f"_done entry for {member!r} must be a ClassDef, got {type(child).__name__}"


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
        if not isinstance(child, nodes.ClassDef):
            raise AssertionError(_cached_child_type_error(member, child))
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


def _dispatch_member_to_child(  # noqa: PLR0911 - distinct Astroid member kinds require separate builder exits.
    self: raw_building.InspectBuilder,
    node: nodes.Module | nodes.ClassDef,
    member: object,
    alias: str,
) -> nodes.NodeNG | object:
    """Dispatch members to the matching Astroid builder."""
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
    obj: object,
    alias: str,
) -> tuple[object | None, bool, bool]:
    """Resolve *alias* from *obj* and report whether the caller should skip it.

    Returns ``(member, pypy__class_getitem__, skip)``. When *skip* is
    ``True`` the attribute could not be retrieved; the caller must attach a
    dummy node.
    """
    pypy__class_getitem__ = IS_PYPY and alias == "__class_getitem__"
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            member = getattr(obj, alias)
    except _IGNORED_GETATTR_ERRORS:
        return None, pypy__class_getitem__, True
    if inspect.ismethod(member) and not pypy__class_getitem__:
        member = member.__func__
    return member, pypy__class_getitem__, False


def _object_build_without_pypy_descriptor_aliases(
    self: raw_building.InspectBuilder,
    node: nodes.Module | nodes.ClassDef,
    obj: object,
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
            attach_dummy_node(node, alias)
            continue
        if pypy__class_getitem__:
            child = _build_builtin_child(self, node, member, alias)
        else:
            child = _dispatch_member_to_child(self, node, member, alias)
        if child is _SKIP:
            continue
        _attach_child_node(node, alias, child)


def main() -> None:
    """Patch Astroid and delegate to Pylint."""
    raw_building.InspectBuilder.object_build = (
        _object_build_without_pypy_descriptor_aliases
    )
    from pylint.lint import Run  # ty: ignore[unresolved-import]

    Run(sys.argv[1:])


if __name__ == "__main__":
    main()
