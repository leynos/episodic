"""Unit tests for the PyPy-backed Pylint wrapper helpers."""

from __future__ import annotations

import builtins
import inspect
import typing as typ

import pytest

from tests.test_pylint_pypy_helpers import (
    FakeBuilder,
    FakeNode,
    ObjectBuildScenario,
    assert_builder_outcome,
    load_pylint_pypy_module,
    make_routing_spies,
    run_object_builder,
    setup_fake_dependencies,
)

if typ.TYPE_CHECKING:
    import types


@pytest.fixture
def pylint_pypy_module(monkeypatch: pytest.MonkeyPatch) -> types.ModuleType:
    """Load the wrapper with fake Astroid modules in place."""
    return load_pylint_pypy_module(monkeypatch)


class _ClassWithClassMethod:
    @classmethod
    def member(cls) -> None:
        """Member used to verify bound-method unwrapping."""


class _ClassWithClassGetItem:
    @classmethod
    def __class_getitem__(cls, item: object) -> object:
        """Member used to verify the PyPy class-getitem exception."""
        return item


def test_resolve_member_unwraps_bound_methods(
    pylint_pypy_module: types.ModuleType,
) -> None:
    """Bound methods are unwrapped before Astroid child construction."""
    node = FakeNode()

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
    node = FakeNode()
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
    node = FakeNode()
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
    builder = FakeBuilder()
    node = FakeNode()
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
    node = FakeNode()
    child = object()

    pylint_pypy_module._attach_child_node(node, "child", child)
    pylint_pypy_module._attach_child_node(node, "child", child)

    assert node.locals["child"] == [child], (
        "_attach_child_node must not duplicate an already-attached child"
    )


def test_object_build_routes_pypy_class_getitem_at_call_site(
    monkeypatch: pytest.MonkeyPatch,
    pylint_pypy_module: types.ModuleType,
) -> None:
    """The object builder keeps PyPy class-getitem handling outside dispatch."""
    scenario = ObjectBuildScenario()
    spies = make_routing_spies(scenario)
    setup_fake_dependencies(
        monkeypatch,
        pylint_pypy_module,
        spies,
    )

    run_object_builder(
        pylint_pypy_module,
        scenario.builder,
        scenario.node,
        scenario.target,
    )

    assert_builder_outcome(scenario, spies)


def test_object_build_ignores_non_string_dir_entries(
    monkeypatch: pytest.MonkeyPatch,
    pylint_pypy_module: types.ModuleType,
) -> None:
    """Non-string ``dir()`` entries are ignored before member resolution."""
    builder = FakeBuilder()
    node = FakeNode()
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
