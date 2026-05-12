"""Unit tests for the PyPy-backed Pylint wrapper helpers."""

import builtins
import importlib.util
import inspect
import sys
import types
import typing as typ
from pathlib import Path

import pytest

_PYLINT_PYPY_PATH = Path(__file__).parents[1] / "tools" / "pylint_pypy.py"


class _FakeClassDef:
    """Minimal Astroid ClassDef stand-in."""


class _FakeModule:
    """Minimal Astroid Module stand-in."""


class _FakeNodeNG:
    """Minimal Astroid NodeNG stand-in."""


class _FakeConst(_FakeNodeNG):
    """Minimal Astroid Const stand-in."""

    def __init__(self, value: object) -> None:
        self.value = value


class _FakeNode:
    """Minimal Astroid node stand-in for local helper tests."""

    def __init__(self) -> None:
        self.locals: dict[str, list[object]] = {}
        self.special_attributes: set[str] = set()

    def add_local_node(self, child: object, alias: str) -> None:
        """Record child attachments like Astroid nodes do."""
        self.locals.setdefault(alias, []).append(child)


class _FakeBuilder:
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


class _ClassWithClassMethod:
    @classmethod
    def member(cls) -> None:
        """Member used to verify bound-method unwrapping."""


class _ClassWithClassGetItem:
    @classmethod
    def __class_getitem__(cls, item: object) -> object:
        """Member used to verify the PyPy class-getitem exception."""
        return item


def _build_fake_astroid_modules() -> dict[str, types.ModuleType]:
    """Create the small Astroid surface needed to import the wrapper."""
    astroid = typ.cast("typ.Any", types.ModuleType("astroid"))
    node_classes = typ.cast("typ.Any", types.ModuleType("astroid.node_classes"))
    nodes = typ.cast("typ.Any", types.ModuleType("astroid.nodes"))
    raw_building = typ.cast("typ.Any", types.ModuleType("astroid.raw_building"))

    node_classes.CONST_CLS = (str, int, float, bool, bytes, type(None))
    nodes.Module = _FakeModule
    nodes.ClassDef = _FakeClassDef
    nodes.NodeNG = _FakeNodeNG
    nodes.Const = _FakeConst
    nodes.const_factory = _FakeConst
    raw_building.IS_PYPY = False
    raw_building.InspectBuilder = _FakeBuilder
    raw_building._build_from_function = lambda node, member, module: object()
    raw_building._safe_has_attribute = hasattr
    raw_building.attach_dummy_node = lambda node, alias: None
    raw_building.build_dummy = lambda member: object()
    raw_building.build_module = lambda alias: _FakeModule()
    raw_building.object_build_class = lambda node, member: _FakeClassDef()
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


@pytest.fixture
def pylint_pypy_module(monkeypatch: pytest.MonkeyPatch) -> types.ModuleType:
    """Load the wrapper with fake Astroid modules in place."""
    for name, module in _build_fake_astroid_modules().items():
        monkeypatch.setitem(sys.modules, name, module)

    spec = importlib.util.spec_from_file_location(
        "pylint_pypy_under_test",
        _PYLINT_PYPY_PATH,
    )
    assert spec is not None, "module spec should not be None"
    assert spec.loader is not None, "module spec loader should not be None"
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


def test_resolve_member_unwraps_bound_methods(
    pylint_pypy_module: types.ModuleType,
) -> None:
    """Bound methods are unwrapped before Astroid child construction."""
    node = _FakeNode()

    member, is_pypy_class_getitem, should_skip = pylint_pypy_module._resolve_member(
        node,
        _ClassWithClassMethod,
        "member",
    )

    assert member is _ClassWithClassMethod.__dict__["member"].__func__, (
        "expected member to be unwrapped bound method"
    )
    assert is_pypy_class_getitem is False, "expected class-getitem flag to be false"
    assert should_skip is False, "expected resolved member not to be skipped"


def test_resolve_member_keeps_pypy_class_getitem_bound(
    monkeypatch: pytest.MonkeyPatch,
    pylint_pypy_module: types.ModuleType,
) -> None:
    """PyPy's ``__class_getitem__`` descriptor alias stays bound."""
    node = _FakeNode()
    monkeypatch.setattr(pylint_pypy_module, "IS_PYPY", True)

    member, is_pypy_class_getitem, should_skip = pylint_pypy_module._resolve_member(
        node,
        _ClassWithClassGetItem,
        "__class_getitem__",
    )

    assert inspect.ismethod(member), "expected PyPy class-getitem member to stay bound"
    assert (
        member.__func__ is _ClassWithClassGetItem.__dict__["__class_getitem__"].__func__
    ), "expected bound member to reference original class-getitem function"
    assert is_pypy_class_getitem is True, "expected class-getitem flag to be true"
    assert should_skip is False, "expected PyPy class-getitem member not to be skipped"


def test_resolve_member_attaches_dummy_when_getattr_fails(
    monkeypatch: pytest.MonkeyPatch,
    pylint_pypy_module: types.ModuleType,
) -> None:
    """Getattr failures attach Astroid's dummy node and signal skip."""
    node = _FakeNode()
    calls: list[tuple[object, str]] = []

    def fake_attach_dummy_node(target_node: object, alias: str) -> None:
        calls.append((target_node, alias))

    monkeypatch.setattr(
        pylint_pypy_module,
        "attach_dummy_node",
        fake_attach_dummy_node,
    )

    member, is_pypy_class_getitem, should_skip = pylint_pypy_module._resolve_member(
        node,
        _ClassWithClassMethod,
        "missing",
    )

    assert member is None, "expected failed member lookup to return None"
    assert is_pypy_class_getitem is False, (
        "expected missing member not to be class-getitem"
    )
    assert should_skip is True, "expected failed member lookup to signal skip"
    assert calls == [(node, "missing")], "expected failed lookup to attach dummy node"


def test_dispatch_member_to_child_routes_builtins(
    monkeypatch: pytest.MonkeyPatch,
    pylint_pypy_module: types.ModuleType,
) -> None:
    """Builtins are routed through the dedicated builtin builder."""
    builder = _FakeBuilder()
    node = _FakeNode()
    child = object()

    def fake_build_builtin_child(
        builder_arg: object,
        node_arg: object,
        member_arg: object,
        alias_arg: str,
    ) -> object:
        assert builder_arg is builder, "expected dispatch to pass builder through"
        assert node_arg is node, "expected dispatch to pass node through"
        assert member_arg is len, "expected dispatch to pass builtin member through"
        assert alias_arg == "len", "expected dispatch to pass builtin alias through"
        return child

    monkeypatch.setattr(
        pylint_pypy_module,
        "_build_builtin_child",
        fake_build_builtin_child,
    )

    result = pylint_pypy_module._dispatch_member_to_child(builder, node, len, "len")

    assert result is child, "expected builtin dispatch to return builder child"


def test_attach_child_node_avoids_duplicate_locals(
    pylint_pypy_module: types.ModuleType,
) -> None:
    """Child attachment preserves Astroid's existing-local guard."""
    node = _FakeNode()
    child = object()

    pylint_pypy_module._attach_child_node(node, "child", child)
    pylint_pypy_module._attach_child_node(node, "child", child)

    assert node.locals["child"] == [child], "expected duplicate child not to be added"


def test_object_build_routes_pypy_class_getitem_at_call_site(
    monkeypatch: pytest.MonkeyPatch,
    pylint_pypy_module: types.ModuleType,
) -> None:
    """The object builder keeps PyPy class-getitem handling outside dispatch."""
    builder = _FakeBuilder()
    node = _FakeNode()
    target = object()
    pypy_child = object()
    ordinary_child = object()

    def fake_dir(obj: object) -> list[object]:
        assert obj is target, "expected object builder to call dir on target object"
        return ["__class_getitem__", object(), "ordinary"]

    def fake_resolve_member(
        node_arg: object,
        obj: object,
        alias: str,
    ) -> tuple[object, bool, bool]:
        assert node_arg is node, "expected resolver to receive target node"
        assert obj is target, "expected resolver to receive target object"
        return object(), alias == "__class_getitem__", False

    def fake_build_builtin_child(
        builder_arg: object,
        node_arg: object,
        member: object,
        alias: str,
    ) -> object:
        assert builder_arg is builder, "expected builtin builder to receive builder"
        assert node_arg is node, "expected builtin builder to receive node"
        assert alias == "__class_getitem__", "expected PyPy alias to use builtin branch"
        return pypy_child

    def fake_dispatch_member_to_child(
        builder_arg: object,
        node_arg: object,
        member: object,
        alias: str,
    ) -> object:
        assert builder_arg is builder, "expected dispatcher to receive builder"
        assert node_arg is node, "expected dispatcher to receive node"
        assert alias == "ordinary", "expected ordinary alias to use dispatcher"
        return ordinary_child

    monkeypatch.setattr(builtins, "dir", fake_dir)
    monkeypatch.setattr(pylint_pypy_module, "_resolve_member", fake_resolve_member)
    monkeypatch.setattr(
        pylint_pypy_module,
        "_build_builtin_child",
        fake_build_builtin_child,
    )
    monkeypatch.setattr(
        pylint_pypy_module,
        "_dispatch_member_to_child",
        fake_dispatch_member_to_child,
    )

    pylint_pypy_module._object_build_without_pypy_descriptor_aliases(
        builder,
        node,
        target,
    )

    assert node.locals == {
        "__class_getitem__": [pypy_child],
        "ordinary": [ordinary_child],
    }, "expected object builder to attach PyPy and ordinary children"
