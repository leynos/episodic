"""REST API adapters for Episodic.

This package exposes the Falcon application factory used by runtime adapters
and integration tests, along with the typed dependency contract consumed by
the inbound HTTP adapter.

Examples
--------
>>> from episodic.api import ApiDependencies, create_app
>>> app = create_app(ApiDependencies(uow_factory=uow_factory))  # doctest: +SKIP
"""

from .app import create_app
from .authorization import (
    AuthorizationContext,
    AuthorizationDecision,
    AuthorizationPort,
    PermitAll,
)
from .dependencies import ApiDependencies, ReadinessProbe

__all__ = [
    "ApiDependencies",
    "AuthorizationContext",
    "AuthorizationDecision",
    "AuthorizationPort",
    "PermitAll",
    "ReadinessProbe",
    "create_app",
]
