"""Shared schema constants for reusable reference-document storage."""

from episodic.canonical.domain import (
    ReferenceBindingTargetKind,
    ReferenceDocumentKind,
    ReferenceDocumentLifecycleState,
)

REFERENCE_DOCUMENT_KIND_VALUES = tuple(member.value for member in ReferenceDocumentKind)
REFERENCE_DOCUMENT_LIFECYCLE_STATE_VALUES = tuple(
    member.value for member in ReferenceDocumentLifecycleState
)
REFERENCE_BINDING_TARGET_KIND_VALUES = tuple(
    member.value for member in ReferenceBindingTargetKind
)

TARGET_KIND_SERIES_PROFILE = ReferenceBindingTargetKind.SERIES_PROFILE.value
TARGET_KIND_EPISODE_TEMPLATE = ReferenceBindingTargetKind.EPISODE_TEMPLATE.value
TARGET_KIND_INGESTION_JOB = ReferenceBindingTargetKind.INGESTION_JOB.value

REFERENCE_BINDINGS_TARGET_CHECK_SQL = (
    f"((target_kind = '{TARGET_KIND_SERIES_PROFILE}' "
    "AND series_profile_id IS NOT NULL "
    "AND episode_template_id IS NULL AND ingestion_job_id IS NULL) OR "
    f"(target_kind = '{TARGET_KIND_EPISODE_TEMPLATE}' "
    "AND episode_template_id IS NOT NULL "
    "AND series_profile_id IS NULL AND ingestion_job_id IS NULL) OR "
    f"(target_kind = '{TARGET_KIND_INGESTION_JOB}' "
    "AND ingestion_job_id IS NOT NULL "
    "AND series_profile_id IS NULL AND episode_template_id IS NULL))"
)
REFERENCE_BINDINGS_EFFECTIVE_EPISODE_CHECK_SQL = (
    "(effective_from_episode_id IS NULL OR "
    f"target_kind = '{TARGET_KIND_SERIES_PROFILE}')"
)


__all__ = (
    "REFERENCE_BINDINGS_EFFECTIVE_EPISODE_CHECK_SQL",
    "REFERENCE_BINDINGS_TARGET_CHECK_SQL",
    "REFERENCE_BINDING_TARGET_KIND_VALUES",
    "REFERENCE_DOCUMENT_KIND_VALUES",
    "REFERENCE_DOCUMENT_LIFECYCLE_STATE_VALUES",
    "TARGET_KIND_EPISODE_TEMPLATE",
    "TARGET_KIND_INGESTION_JOB",
    "TARGET_KIND_SERIES_PROFILE",
)
