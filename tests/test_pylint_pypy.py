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


class _ObjectBuildScenario:
    """Shared objects for object-builder orchestration tests."""

    def __init__(self) -> None:
        self.builder = _FakeBuilder()
        self.node = _FakeNode()
        self.target = object()
        self.pypy_child = object()
        self.ordinary_child = object()


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
    assert spec is not None, f"Could not create module spec from {_PYLINT_PYPY_PATH}"
    assert spec.loader is not None, f"Module spec for {_PYLINT_PYPY_PATH} has no loader"
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
        "bound method must be unwrapped to its underlying __func__"
    )
    assert is_pypy_class_getitem is False, (
        "alias 'member' must not be flagged as pypy__class_getitem__"
    )
    assert should_skip is False, (
        "_resolve_member must not signal skip for a resolvable alias"
    )


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

    assert inspect.ismethod(member), (
        "__class_getitem__ must remain a bound method when IS_PYPY is True"
    )
    assert (
        member.__func__ is _ClassWithClassGetItem.__dict__["__class_getitem__"].__func__
    ), "__func__ must point to the underlying classmethod function"
    assert is_pypy_class_getitem is True, (
        "alias '__class_getitem__' must be flagged when IS_PYPY is True"
    )
    assert should_skip is False, (
        "_resolve_member must not signal skip for resolvable __class_getitem__"
    )


def test_resolve_member_signals_skip_when_getattr_fails(
    monkeypatch: pytest.MonkeyPatch,
    pylint_pypy_module: types.ModuleType,
) -> None:
    """Getattr failures return a skip signal without side effects."""
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

    assert member is None, (
        "_resolve_member must return None as member when getattr fails"
    )
    assert is_pypy_class_getitem is False, (
        "alias 'missing' must not be flagged as pypy__class_getitem__"
    )
    assert should_skip is True, "_resolve_member must signal skip when getattr raises"
    assert not calls, "_resolve_member must not attach dummy nodes directly"


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
        assert builder_arg is builder, "builder argument must be forwarded unchanged"
        assert node_arg is node, "node argument must be forwarded unchanged"
        assert member_arg is len, "member argument must be forwarded unchanged"
        assert alias_arg == "len", "alias argument must be forwarded unchanged"
        return child

    monkeypatch.setattr(
        pylint_pypy_module,
        "_build_builtin_child",
        fake_build_builtin_child,
    )

    result = pylint_pypy_module._dispatch_member_to_child(builder, node, len, "len")

    assert result is child, (
        "_dispatch_member_to_child must return the value from _build_builtin_child"
    )


def test_attach_child_node_avoids_duplicate_locals(
    pylint_pypy_module: types.ModuleType,
) -> None:
    """Child attachment preserves Astroid's existing-local guard."""
    node = _FakeNode()
    child = object()

    pylint_pypy_module._attach_child_node(node, "child", child)
    pylint_pypy_module._attach_child_node(node, "child", child)

    assert node.locals["child"] == [child], (
        "_attach_child_node must not duplicate an already-attached child"
    )


def setup_fake_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    pylint_pypy_module: types.ModuleType,
    scenario: _ObjectBuildScenario,
) -> list[tuple[object, str]]:
    """Register fake object-builder dependencies and return dummy calls."""

    def fake_dir(obj: object) -> list[object]:
        assert obj is scenario.target, (
            "obj passed to fake_dir must be the target object"
        )
        return ["__class_getitem__", object(), "missing", "ordinary"]

    def fake_resolve_member(
        node_arg: object,
        obj: object,
        alias: str,
    ) -> tuple[object, bool, bool]:
        assert node_arg is scenario.node, "node argument must be forwarded unchanged"
        assert obj is scenario.target, "obj argument must be forwarded unchanged"
        if alias == "missing":
            return None, False, True
        return object(), alias == "__class_getitem__", False

    def fake_build_builtin_child(
        builder_arg: object,
        node_arg: object,
        member: object,
        alias: str,
    ) -> object:
        assert builder_arg is scenario.builder, (
            "builder argument must be forwarded unchanged"
        )
        assert node_arg is scenario.node, "node argument must be forwarded unchanged"
        assert alias == "__class_getitem__", (
            "_build_builtin_child must only be called for __class_getitem__"
        )
        return scenario.pypy_child

    def fake_dispatch_member_to_child(
        builder_arg: object,
        node_arg: object,
        member: object,
        alias: str,
    ) -> object:
        assert builder_arg is scenario.builder, (
            "builder argument must be forwarded unchanged"
        )
        assert node_arg is scenario.node, "node argument must be forwarded unchanged"
        assert alias == "ordinary", (
            "_dispatch_member_to_child must only be called for ordinary aliases"
        )
        return scenario.ordinary_child

    dummy_calls: list[tuple[object, str]] = []

    def fake_attach_dummy_node(node_arg: object, alias: str) -> None:
        dummy_calls.append((node_arg, alias))

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
    monkeypatch.setattr(pylint_pypy_module, "attach_dummy_node", fake_attach_dummy_node)
    return dummy_calls


def run_object_builder(
    pylint_pypy_module: types.ModuleType,
    builder: _FakeBuilder,
    node: _FakeNode,
    target: object,
) -> None:
    """Run the patched object builder with the provided test doubles."""
    pylint_pypy_module._object_build_without_pypy_descriptor_aliases(
        builder,
        node,
        target,
    )


def assert_builder_outcome(
    scenario: _ObjectBuildScenario,
    dummy_calls: list[tuple[object, str]],
) -> None:
    """Verify child attachment and skipped-alias dummy handling."""
    assert scenario.node.locals == {
        "__class_getitem__": [scenario.pypy_child],
        "ordinary": [scenario.ordinary_child],
    }, "locals must contain exactly the two children from their respective builders"
    assert dummy_calls == [(scenario.node, "missing")], (
        "object builder must attach a dummy node for skipped aliases"
    )


def test_object_build_routes_pypy_class_getitem_at_call_site(
    monkeypatch: pytest.MonkeyPatch,
    pylint_pypy_module: types.ModuleType,
) -> None:
    """The object builder keeps PyPy class-getitem handling outside dispatch."""
    scenario = _ObjectBuildScenario()
    dummy_calls = setup_fake_dependencies(
        monkeypatch,
        pylint_pypy_module,
        scenario,
    )

    run_object_builder(
        pylint_pypy_module,
        scenario.builder,
        scenario.node,
        scenario.target,
    )

    assert_builder_outcome(scenario, dummy_calls)


def test_object_build_ignores_non_string_dir_entries(
    monkeypatch: pytest.MonkeyPatch,
    pylint_pypy_module: types.ModuleType,
) -> None:
    """Non-string ``dir()`` entries are ignored before member resolution."""
    builder = _FakeBuilder()
    node = _FakeNode()
    target = object()
    resolved_aliases: list[str] = []

    class _Alias(str):  # noqa: FURB189 - str subclass handling is under test.
        """String subclass used to prove str-like aliases are accepted."""

    def fake_dir(obj: object) -> list[object]:
        assert obj is target, "obj passed to fake_dir must be the target object"
        return [object(), 123, _Alias("child")]

    def fake_resolve_member(
        node_arg: object,
        obj: object,
        alias: str,
    ) -> tuple[object, bool, bool]:
        assert node_arg is node, "node argument must be forwarded unchanged"
        assert obj is target, "obj argument must be forwarded unchanged"
        resolved_aliases.append(alias)
        return object(), False, False

    monkeypatch.setattr(builtins, "dir", fake_dir)
    monkeypatch.setattr(pylint_pypy_module, "_resolve_member", fake_resolve_member)
    monkeypatch.setattr(
        pylint_pypy_module,
        "_dispatch_member_to_child",
        lambda builder_arg, node_arg, member, alias: object(),
    )

    pylint_pypy_module._object_build_without_pypy_descriptor_aliases(
        builder,
        node,
        target,
    )

    assert resolved_aliases == ["child"], (
        "object builder must resolve only string and str-subclass aliases"
    )
    assert list(node.locals) == ["child"], (
        "object builder must not attach locals for non-string aliases"
    )
