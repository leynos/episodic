"""Shared types for the Falcon canonical API adapter.

This module defines ``UowFactory``, a callable alias used by API adapters to
obtain a ``CanonicalUnitOfWork`` instance when handling requests.

Example
-------
Define and use a unit-of-work factory:

>>> factory: UowFactory = (  # doctest: +SKIP
...     lambda: SqlAlchemyUnitOfWork(session_factory)
... )
>>> uow = factory()  # doctest: +SKIP
"""

from __future__ import annotations

import collections.abc as cabc
import typing as typ

if typ.TYPE_CHECKING:
    from episodic.canonical.ports import CanonicalUnitOfWork

type UowFactory = cabc.Callable[[], CanonicalUnitOfWork]
