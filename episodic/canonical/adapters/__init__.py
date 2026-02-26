"""Reference adapters for multi-source ingestion ports."""

from __future__ import annotations

from .normalizer import InMemorySourceNormalizer
from .resolver import HighestWeightConflictResolver
from .weighting import DefaultWeightingStrategy

__all__ = [
    "DefaultWeightingStrategy",
    "HighestWeightConflictResolver",
    "InMemorySourceNormalizer",
]
