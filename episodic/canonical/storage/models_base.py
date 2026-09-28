"""Canonical SQLAlchemy enum types and shared ORM base import."""

import sqlalchemy as sa

from episodic.canonical.domain import (
    ApprovalState,
    EpisodeStatus,
    GenerationRunStatus,
    IngestionStatus,
    IntakeState,
    ReferenceBindingTargetKind,
    ReferenceDocumentKind,
    ReferenceDocumentLifecycleState,
    WorkflowCheckpointStatus,
)
from episodic.canonical.generation_quality import QaStatus, QualityMode
from episodic.canonical.idempotency import IdempotencyState
from episodic.canonical.ingestion_sources import AttachmentKind
from episodic.canonical.uploads import UploadState
from episodic.sqlalchemy_base import Base as Base

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
INTAKE_STATE = sa.Enum(
    IntakeState,
    name="intake_state",
    values_callable=lambda enum_cls: [item.value for item in enum_cls],
)
UPLOAD_STATE = sa.Enum(
    UploadState,
    name="upload_state",
    values_callable=lambda enum_cls: [item.value for item in enum_cls],
)
ATTACHMENT_KIND = sa.Enum(
    AttachmentKind,
    name="attachment_kind",
    values_callable=lambda enum_cls: [item.value for item in enum_cls],
)
IDEMPOTENCY_STATE = sa.Enum(
    IdempotencyState,
    name="idempotency_state",
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
GENERATION_RUN_STATUS = sa.Enum(
    GenerationRunStatus,
    name="generation_run_status",
    values_callable=lambda enum_cls: [item.value for item in enum_cls],
)
QUALITY_MODE = sa.Enum(
    QualityMode,
    name="quality_mode",
    values_callable=lambda enum_cls: [item.value for item in enum_cls],
)
QA_STATUS = sa.Enum(
    QaStatus,
    name="qa_status",
    values_callable=lambda enum_cls: [item.value for item in enum_cls],
)
