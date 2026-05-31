"""Shared pagination value object for canonical list endpoints and services.

This module defines :class:`Pagination`, a small frozen value object that
carries the ``limit`` and ``offset`` page selectors used by every paginated
canonical service and its API adapter. It lives in the domain-ports layer so
both inbound adapters (Falcon resources) and application services can share
the same value type without one importing the other.
"""

import dataclasses as dc

__all__ = ["Pagination"]


@dc.dataclass(frozen=True, slots=True)
class Pagination:
    """Page selectors for a paginated list operation.

    Parameters
    ----------
    limit : int
        Maximum number of items to return for the page. Callers are expected to
        have already validated the bound (typically ``1 <= limit <= 100``).
    offset : int
        Number of items to skip before the page begins. Callers are expected to
        have already validated that ``offset >= 0``.
    """

    limit: int
    offset: int
