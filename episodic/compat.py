"""Compatibility helpers for optional Rust extensions."""

from __future__ import annotations

import importlib
import typing as typ

if typ.TYPE_CHECKING:
    import collections.abc as cabc


def _load_rust_hello() -> cabc.Callable[[], str] | None:
    try:
        module = importlib.import_module("episodic_rust")
    except ModuleNotFoundError:  # pragma: no cover - optional extension
        return None
    hello = getattr(module, "hello", None)
    if hello is None:
        return None
    return typ.cast("cabc.Callable[[], str]", hello)


_rust_hello = _load_rust_hello()


def _py_hello() -> str:
    """Fallback hello implementation."""
    return "hello"


def _resolve_hello() -> cabc.Callable[[], str]:
    """Return the best available hello implementation."""
    if _rust_hello is not None:
        return _rust_hello
    return _py_hello


def hello() -> str:
    """Return a hello message using the best available implementation."""
    return _resolve_hello()()


__all__ = ["hello"]
