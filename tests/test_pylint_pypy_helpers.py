"""Test doubles and orchestration helpers for PyPy-backed Pylint tests."""

from __future__ import annotations

import builtins
import dataclasses
import importlib.util
import sys
import types
import typing as typ
from pathlib import Path

if typ.TYPE_CHECKING:
    import pytest

_PYLINT_PYPY_PATH = Path(__file__).parents[1] / "tools" / "pylint_pypy.py"


class FakeClassDef:
    """Minimal Astroid ClassDef stand-in."""


class FakeModule:
    """Minimal Astroid Module stand-in."""


class FakeNodeNG:
    """Minimal Astroid NodeNG stand-in."""


class FakeConst(FakeNodeNG):
    """Minimal Astroid Const stand-in."""

    def __init__(self, value: object) -> None:
        self.value = value


class FakeNode:
    """Minimal Astroid node stand-in for local helper tests."""

    def __init__(self) -> None:
        self.locals: dict[str, list[object]] = {}
        self.special_attributes: set[str] = set()

    def add_local_node(self, child: object, alias: str) -> None:
        """Record child attachments like Astroid nodes do."""
        self.locals.setdefault(alias, []).append(child)


class FakeBuilder:
    """Minimal InspectBuilder stand-in for local helper tests."""

    def __init__(self) -> None:
        self._done: dict[object, object] = {}
        self._module = "test-module"
        self.object_build_calls: list[tuple[object, object]] = []

    def imported_member(self, node: object, member: object, alias: str) -> bool:
        """Treat test members as local unless a test overrides this method."""
        return False

    def object_build(self, child: object, member: object) -> None:
        """Record recursive object-build calls."""
        self.object_build_calls.append((child, member))


class ObjectBuildScenario:
    """Shared objects for object-builder orchestration tests."""

    def __init__(self) -> None:
        self.builder = FakeBuilder()
        self.node = FakeNode()
        self.target = object()
        self.pypy_child = object()
        self.ordinary_child = object()


@dataclasses.dataclass
class RoutingSpies:
    """Spy callables and call logs for object-builder routing tests."""

    fake_dir: object
    fake_resolve_member: object
    fake_build_builtin_child: object
    fake_dispatch_member_to_child: object
    fake_attach_child_node: object
    builtin_calls: list[str]
    dispatch_calls: list[str]
    attach_calls: list[tuple[object, str]]


def build_fake_astroid_modules() -> dict[str, types.ModuleType]:
    """Create the small Astroid surface needed to import the wrapper."""
    astroid = typ.cast("typ.Any", types.ModuleType("astroid"))
    node_classes = typ.cast("typ.Any", types.ModuleType("astroid.node_classes"))
    nodes = typ.cast("typ.Any", types.ModuleType("astroid.nodes"))
    raw_building = typ.cast("typ.Any", types.ModuleType("astroid.raw_building"))

    node_classes.CONST_CLS = (str, int, float, bool, bytes, type(None))
    nodes.Module = FakeModule
    nodes.ClassDef = FakeClassDef
    nodes.NodeNG = FakeNodeNG
    nodes.Const = FakeConst
    nodes.const_factory = FakeConst
    raw_building.IS_PYPY = False
    raw_building.InspectBuilder = FakeBuilder
    raw_building._build_from_function = lambda node, member, module: object()
    raw_building._safe_has_attribute = hasattr
    raw_building.attach_dummy_node = lambda node, alias: None
    raw_building.build_dummy = lambda member: object()
    raw_building.build_module = lambda alias: FakeModule()
    raw_building.object_build_class = lambda node, member: FakeClassDef()
    raw_building.object_build_datadescriptor = lambda node, member: object()
    raw_building.object_build_methoddescriptor = lambda node, member: object()

    astroid.node_classes = node_classes
    astroid.nodes = nodes
    astroid.raw_building = raw_building
    return {
        "astroid": astroid,
        "astroid.node_classes": node_classes,
        "astroid.nodes": nodes,
        "astroid.raw_building": raw_building,
    }


def load_pylint_pypy_module(monkeypatch: pytest.MonkeyPatch) -> types.ModuleType:
    """Load the wrapper with fake Astroid modules in place."""
    for name, module in build_fake_astroid_modules().items():
        monkeypatch.setitem(sys.modules, name, module)

    spec = importlib.util.spec_from_file_location(
        "pylint_pypy_under_test",
        _PYLINT_PYPY_PATH,
    )
    assert spec is not None, f"Could not create module spec from {_PYLINT_PYPY_PATH}"
    assert spec.loader is not None, f"Module spec for {_PYLINT_PYPY_PATH} has no loader"
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


def make_routing_spies(
    node: object,
    builder: object,
    target: object,
    pypy_child: object,
    ordinary_child: object,
) -> RoutingSpies:
    """Build spy callables for routing verification."""
    builtin_calls: list[str] = []
    dispatch_calls: list[str] = []
    attach_calls: list[tuple[object, str]] = []

    def fake_dir(obj: object) -> list[object]:
        assert obj is target, "obj passed to fake_dir must be the target object"
        return ["__class_getitem__", object(), "missing", "ordinary"]

    def fake_resolve_member(
        node_arg: object,
        obj: object,
        alias: str,
    ) -> tuple[object, bool, bool]:
        assert node_arg is node, "node argument must be forwarded unchanged"
        assert obj is target, "obj argument must be forwarded unchanged"
        if alias == "missing":
            return None, False, True
        return object(), alias == "__class_getitem__", False

    def fake_build_builtin_child(
        builder_arg: object,
        node_arg: object,
        member: object,
        alias: str,
    ) -> object:
        assert builder_arg is builder, "builder argument must be forwarded unchanged"
        assert node_arg is node, "node argument must be forwarded unchanged"
        assert alias == "__class_getitem__", (
            "_build_builtin_child must only be called for __class_getitem__"
        )
        builtin_calls.append(alias)
        return pypy_child

    def fake_dispatch_member_to_child(
        builder_arg: object,
        node_arg: object,
        member: object,
        alias: str,
    ) -> object:
        assert builder_arg is builder, "builder argument must be forwarded unchanged"
        assert node_arg is node, "node argument must be forwarded unchanged"
        assert alias == "ordinary", (
            "_dispatch_member_to_child must only be called for ordinary aliases"
        )
        dispatch_calls.append(alias)
        return ordinary_child

    def fake_attach_child_node(node_arg: object, alias: str) -> None:
        attach_calls.append((node_arg, alias))

    return RoutingSpies(
        fake_dir=fake_dir,
        fake_resolve_member=fake_resolve_member,
        fake_build_builtin_child=fake_build_builtin_child,
        fake_dispatch_member_to_child=fake_dispatch_member_to_child,
        fake_attach_child_node=fake_attach_child_node,
        builtin_calls=builtin_calls,
        dispatch_calls=dispatch_calls,
        attach_calls=attach_calls,
    )


def setup_fake_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    pylint_pypy_module: types.ModuleType,
    spies: RoutingSpies,
) -> None:
    """Register fake object-builder dependencies."""
    monkeypatch.setattr(builtins, "dir", spies.fake_dir)
    monkeypatch.setattr(
        pylint_pypy_module, "_resolve_member", spies.fake_resolve_member
    )
    monkeypatch.setattr(
        pylint_pypy_module,
        "_build_builtin_child",
        spies.fake_build_builtin_child,
    )
    monkeypatch.setattr(
        pylint_pypy_module,
        "_dispatch_member_to_child",
        spies.fake_dispatch_member_to_child,
    )
    monkeypatch.setattr(
        pylint_pypy_module, "attach_dummy_node", spies.fake_attach_child_node
    )


def run_object_builder(
    pylint_pypy_module: types.ModuleType,
    builder: FakeBuilder,
    node: FakeNode,
    target: object,
) -> None:
    """Run the patched object builder with the provided test doubles."""
    pylint_pypy_module._object_build_without_pypy_descriptor_aliases(
        builder,
        node,
        target,
    )


def assert_builder_outcome(
    scenario: ObjectBuildScenario,
    spies: RoutingSpies,
) -> None:
    """Verify child attachment and skipped-alias dummy handling."""
    assert scenario.node.locals == {
        "__class_getitem__": [scenario.pypy_child],
        "ordinary": [scenario.ordinary_child],
    }, "locals must contain exactly the two children from their respective builders"
    assert spies.attach_calls == [(scenario.node, "missing")], (
        "object builder must attach a dummy node for skipped aliases"
    )
