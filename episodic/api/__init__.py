"""REST API adapters for Episodic.

This package exposes the Falcon application factory used by runtime adapters
and integration tests.

Examples
--------
>>> from episodic.api import create_app
>>> app = create_app(uow_factory)  # doctest: +SKIP
"""

from __future__ import annotations

from .app import create_app

__all__ = ["create_app"]
