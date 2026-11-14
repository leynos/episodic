"""File-backed pricing catalogue adapters.

This package provides ``FilePricingCatalogue`` for loading immutable YAML
pricing snapshots and resolving deterministic prices without a live provider or
database lookup. Construct it with a snapshot directory, then call
``await catalogue.resolve(subject)`` to obtain the matching pricing snapshot;
pass ``at=`` an aware instant to resolve as of a recorded call.
"""

from ._errors import PricingCatalogueError
from .file_loader import FilePricingCatalogue

__all__ = ["FilePricingCatalogue", "PricingCatalogueError"]
