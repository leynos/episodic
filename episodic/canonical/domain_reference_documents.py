"""Reusable reference-document and reference-binding domain models."""

import dataclasses as dc
import typing as typ

from .domain_enums import (
    ReferenceBindingTargetKind,
    ReferenceDocumentKind,
    ReferenceDocumentLifecycleState,
)

if typ.TYPE_CHECKING:
    import datetime as dt
    import uuid

    from .domain_enums import JsonMapping


@dc.dataclass(frozen=True, slots=True)
class ReferenceDocument:
    """Reusable reference document metadata independent of ingestion jobs."""

    id: uuid.UUID
    owner_series_profile_id: uuid.UUID
    kind: ReferenceDocumentKind
    lifecycle_state: ReferenceDocumentLifecycleState
    metadata: JsonMapping
    created_at: dt.datetime
    updated_at: dt.datetime
    lock_version: int = 1

    def __post_init__(self) -> None:
        """Validate optimistic-lock invariants."""
        if not isinstance(self.lock_version, int) or self.lock_version < 1:
            msg = "lock_version must be a positive integer."
            raise ValueError(msg)


@dc.dataclass(frozen=True, slots=True)
class ReferenceDocumentRevision:
    """Immutable content revision for a reusable reference document."""

    id: uuid.UUID
    reference_document_id: uuid.UUID
    content: JsonMapping
    content_hash: str
    author: str | None
    change_note: str | None
    created_at: dt.datetime

    def __post_init__(self) -> None:
        """Validate content-hash invariants."""
        if self.content_hash.strip() == "":
            msg = "content_hash must be a non-empty string."
            raise ValueError(msg)


@dc.dataclass(frozen=True, slots=True)
class ReferenceBinding:
    """Pinned reusable reference revision linked to one target context."""

    id: uuid.UUID
    reference_document_revision_id: uuid.UUID
    target_kind: ReferenceBindingTargetKind
    series_profile_id: uuid.UUID | None
    episode_template_id: uuid.UUID | None
    ingestion_job_id: uuid.UUID | None
    effective_from_episode_id: uuid.UUID | None
    created_at: dt.datetime

    def __post_init__(self) -> None:
        """Validate target and applicability invariants."""
        self._validate_single_target()
        self._validate_target_kind_matches()
        self._validate_effective_from_constraint()

    def _validate_single_target(self) -> None:
        """Validate that exactly one target identifier is populated."""
        target_pairs = (
            (ReferenceBindingTargetKind.SERIES_PROFILE, self.series_profile_id),
            (
                ReferenceBindingTargetKind.EPISODE_TEMPLATE,
                self.episode_template_id,
            ),
            (ReferenceBindingTargetKind.INGESTION_JOB, self.ingestion_job_id),
        )
        populated_targets = [kind for kind, value in target_pairs if value is not None]
        if len(populated_targets) != 1:
            msg = "ReferenceBinding must set exactly one target identifier."
            raise ValueError(msg)

    def _validate_target_kind_matches(self) -> None:
        """Validate target_kind matches the populated target identifier."""
        target_mapping = {
            ReferenceBindingTargetKind.SERIES_PROFILE: self.series_profile_id,
            ReferenceBindingTargetKind.EPISODE_TEMPLATE: self.episode_template_id,
            ReferenceBindingTargetKind.INGESTION_JOB: self.ingestion_job_id,
        }
        populated_targets = [
            kind for kind, value in target_mapping.items() if value is not None
        ]
        populated_target = populated_targets[0]
        if populated_target is not self.target_kind:
            msg = "ReferenceBinding target_kind does not match populated target."
            raise ValueError(msg)

    def _validate_effective_from_constraint(self) -> None:
        """Validate effective_from applicability constraint."""
        if (
            self.effective_from_episode_id is not None
            and self.target_kind is not ReferenceBindingTargetKind.SERIES_PROFILE
        ):
            msg = (
                "ReferenceBinding effective_from_episode_id is only valid for "
                "series_profile targets."
            )
            raise ValueError(msg)
