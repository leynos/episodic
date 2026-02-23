"""Shared types for the Falcon canonical API adapter."""

from __future__ import annotations

import collections.abc as cabc
import typing as typ

if typ.TYPE_CHECKING:
    from episodic.canonical.ports import CanonicalUnitOfWork

type UowFactory = cabc.Callable[[], CanonicalUnitOfWork]
