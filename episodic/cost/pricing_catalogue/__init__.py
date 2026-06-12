"""File-backed pricing catalogue adapters.

This package provides ``FilePricingCatalogue`` for loading immutable YAML
pricing snapshots and resolving deterministic prices without a live provider or
database lookup. Construct it with a snapshot directory, then call
``await catalogue.resolve(provider, model, operation, BillingPeriodKey("2026-06"))``
to obtain the matching pricing snapshot.
"""

from .file_loader import FilePricingCatalogue

__all__ = ["FilePricingCatalogue"]
