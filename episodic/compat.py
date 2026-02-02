"""Runtime compatibility helpers for optional extensions."""

from __future__ import annotations

import typing as typ

PACKAGE_NAME = "episodic"


def _resolve_hello() -> typ.Callable[[], str]:
    """Select the Rust-backed hello function when available."""
    try:  # pragma: no cover - Rust optional
        rust = __import__(f"_{PACKAGE_NAME}_rs")
    except ModuleNotFoundError:  # pragma: no cover - Python fallback
        from .pure import hello as pure_hello

        return pure_hello

    try:
        rust_hello = rust.hello
    except AttributeError:  # pragma: no cover - Rust fallback
        from .pure import hello as pure_hello

        return pure_hello

    return typ.cast("typ.Callable[[], str]", rust_hello)


hello = _resolve_hello()

__all__ = ["hello"]
