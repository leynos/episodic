"""Tests for the episodic.compat shim behaviour."""

import typing as typ

from episodic import compat

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    import pytest


def _dummy_hello(name: str) -> cabc.Callable[[], str]:
    def impl() -> str:
        return name

    return impl


def test_resolve_hello_prefers_rust_extension(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_resolve_hello should prefer the Rust-backed implementation."""
    rust_impl = _dummy_hello("rust")
    py_impl = _dummy_hello("py")

    monkeypatch.setattr(compat, "_rust_hello", rust_impl, raising=False)
    monkeypatch.setattr(compat, "_py_hello", py_impl, raising=False)

    resolved = compat._resolve_hello()

    assert resolved is rust_impl, "Expected values to match"
    assert resolved() == "rust", "Expected values to match"


def test_resolve_hello_falls_back_to_python(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_resolve_hello should fall back to the Python implementation."""
    py_impl = _dummy_hello("py")

    monkeypatch.setattr(compat, "_rust_hello", None, raising=False)
    monkeypatch.setattr(compat, "_py_hello", py_impl, raising=False)

    resolved = compat._resolve_hello()

    assert resolved is py_impl, "Expected values to match"
    assert resolved() == "py", "Expected values to match"


def test_compat_hello_remains_callable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """compat.hello should be callable regardless of backing implementation."""
    py_impl = _dummy_hello("py")

    monkeypatch.setattr(compat, "_rust_hello", None, raising=False)
    monkeypatch.setattr(compat, "_py_hello", py_impl, raising=False)

    assert compat.hello() == "py", "Expected values to match"
