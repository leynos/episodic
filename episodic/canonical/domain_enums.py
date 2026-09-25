"""Shared primitive type and lifecycle enumerations for canonical domain models."""

import enum

type JsonMapping = dict[str, object]


class EpisodeStatus(enum.StrEnum):
    """Lifecycle states for canonical episodes."""

    DRAFT = "draft"
    IN_PROGRESS = "in_progress"
    QUALITY_REVIEW = "quality_review"
    EDITORIAL_REVIEW = "editorial_review"
    ON_HOLD = "on_hold"
    REJECTED = "rejected"
    AUDIO_GENERATION = "audio_generation"
    POST_PROCESSING = "post_processing"
    READY_TO_PUBLISH = "ready_to_publish"
    SCHEDULED = "scheduled"
    PUBLISHED = "published"
    UPDATED = "updated"
    FAILED = "failed"
    ARCHIVED = "archived"


class ApprovalState(enum.StrEnum):
    """Approval workflow states for canonical episodes."""

    DRAFT = "draft"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"


class IngestionStatus(enum.StrEnum):
    """Status values for ingestion jobs."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class IntakeState(enum.StrEnum):
    """Source-intake states for pre-generation ingestion jobs."""

    AWAITING_SOURCES = "awaiting_sources"
    READY_FOR_GENERATION = "ready_for_generation"
    CANCELLED = "cancelled"


class ReferenceDocumentKind(enum.StrEnum):
    """Supported reusable reference-document kinds."""

    STYLE_GUIDE = "style_guide"
    HOST_PROFILE = "host_profile"
    GUEST_PROFILE = "guest_profile"
    RESEARCH_BRIEF = "research_brief"


class ReferenceDocumentLifecycleState(enum.StrEnum):
    """Lifecycle states for reusable reference documents."""

    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


class ReferenceBindingTargetKind(enum.StrEnum):
    """Supported target contexts for reusable reference bindings."""

    SERIES_PROFILE = "series_profile"
    EPISODE_TEMPLATE = "episode_template"
    INGESTION_JOB = "ingestion_job"


class WorkflowCheckpointStatus(enum.StrEnum):
    """Lifecycle states for resumable orchestration checkpoints."""

    SUSPENDED = "suspended"
    RESUMED = "resumed"


class GenerationRunStatus(enum.StrEnum):
    """Lifecycle states for user-facing generation runs."""

    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

    def is_terminal(self) -> bool:
        """Return whether this status is a terminal run state."""
        return self in {
            GenerationRunStatus.SUCCEEDED,
            GenerationRunStatus.FAILED,
            GenerationRunStatus.CANCELLED,
        }


class CheckpointStatus(enum.StrEnum):
    """Lifecycle states for user-facing generation checkpoints."""

    CREATED = "created"
    RESPONDED = "responded"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"

    def is_terminal(self) -> bool:
        """Return whether this status is a terminal checkpoint state."""
        return self is not CheckpointStatus.CREATED


class CheckpointAction(enum.StrEnum):
    """Reviewer actions accepted for a generation checkpoint."""

    APPROVE = "approve"
    REQUEST_CHANGES = "request_changes"
    EDIT = "edit"
