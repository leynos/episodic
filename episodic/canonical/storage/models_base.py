"""Shared SQLAlchemy metadata and enum types for canonical storage."""

import sqlalchemy as sa
from sqlalchemy import orm

from episodic.canonical.domain import (
    ApprovalState,
    EpisodeStatus,
    IngestionStatus,
    ReferenceBindingTargetKind,
    ReferenceDocumentKind,
    ReferenceDocumentLifecycleState,
    WorkflowCheckpointStatus,
)


class Base(orm.DeclarativeBase):
    """Base class for canonical SQLAlchemy models.

    Notes
    -----
    Alembic and test scaffolding rely on ``Base.metadata`` when applying
    migrations or creating schema definitions.
    """


EPISODE_STATUS = sa.Enum(
    EpisodeStatus,
    name="episode_status",
    values_callable=lambda enum_cls: [item.value for item in enum_cls],
)
APPROVAL_STATE = sa.Enum(
    ApprovalState,
    name="approval_state",
    values_callable=lambda enum_cls: [item.value for item in enum_cls],
)
INGESTION_STATUS = sa.Enum(
    IngestionStatus,
    name="ingestion_status",
    values_callable=lambda enum_cls: [item.value for item in enum_cls],
)
REFERENCE_DOCUMENT_KIND = sa.Enum(
    ReferenceDocumentKind,
    name="reference_document_kind",
    values_callable=lambda enum_cls: [item.value for item in enum_cls],
)
REFERENCE_DOCUMENT_LIFECYCLE_STATE = sa.Enum(
    ReferenceDocumentLifecycleState,
    name="reference_document_lifecycle_state",
    values_callable=lambda enum_cls: [item.value for item in enum_cls],
)
REFERENCE_BINDING_TARGET_KIND = sa.Enum(
    ReferenceBindingTargetKind,
    name="reference_binding_target_kind",
    values_callable=lambda enum_cls: [item.value for item in enum_cls],
)
WORKFLOW_CHECKPOINT_STATUS = sa.Enum(
    WorkflowCheckpointStatus,
    name="workflow_checkpoint_status",
    values_callable=lambda enum_cls: [item.value for item in enum_cls],
)
