"""Tests for immutable reference-document storage schema constants."""

from types import MappingProxyType

from episodic.canonical.domain import ReferenceBindingTargetKind
from episodic.canonical.storage.reference_document_schema import (
    REFERENCE_BINDING_TARGET_KIND_VALUES,
)


def test_reference_binding_target_kind_values_are_immutable() -> None:
    """Expose target-kind schema values through an immutable mapping."""
    assert isinstance(REFERENCE_BINDING_TARGET_KIND_VALUES, MappingProxyType), (
        "reference-binding target-kind values must not expose mutable state"
    )
    assert REFERENCE_BINDING_TARGET_KIND_VALUES == {
        ReferenceBindingTargetKind.SERIES_PROFILE: "series_profile",
        ReferenceBindingTargetKind.EPISODE_TEMPLATE: "episode_template",
        ReferenceBindingTargetKind.INGESTION_JOB: "ingestion_job",
    }, "immutable target-kind values must preserve the schema constants"
