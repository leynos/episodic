"""Reference adapters for multi-source ingestion ports."""

from __future__ import annotations

from .normaliser import InMemorySourceNormaliser
from .resolver import HighestWeightConflictResolver
from .weighting import DefaultWeightingStrategy

__all__ = [
    "DefaultWeightingStrategy",
    "HighestWeightConflictResolver",
    "InMemorySourceNormaliser",
]
