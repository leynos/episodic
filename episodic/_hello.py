"""Resolve optional Rust bindings for the public hello function."""

from __future__ import annotations

PACKAGE_NAME = "episodic"

try:  # pragma: no cover - Rust optional
    rust = __import__(f"_{PACKAGE_NAME}_rs")
except ModuleNotFoundError:  # pragma: no cover - Python fallback
    from .pure import hello
else:
    hello = rust.hello
