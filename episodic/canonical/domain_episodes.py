"""Canonical episode and TEI-update domain models."""

import dataclasses as dc
import typing as typ

from .domain_validation import (
    _require_positive_integer,
    _require_value,
    _validate_non_empty_text,
    _validate_optional_text,
)

if typ.TYPE_CHECKING:
    import datetime as dt
    import uuid

    from .domain_enums import ApprovalState, EpisodeStatus, JsonMapping
    from .generation_quality import QaStatus


@dc.dataclass(frozen=True, slots=True)
class CanonicalEpisode:
    """Canonical episode representation."""

    id: uuid.UUID
    series_profile_id: uuid.UUID
    tei_header_id: uuid.UUID
    title: str
    tei_xml: str
    status: EpisodeStatus
    approval_state: ApprovalState
    created_at: dt.datetime
    updated_at: dt.datetime
    tei_revision: int = 1
    tei_content_hash: str | None = None
    qa_status: QaStatus | None = None
    last_generation_run_id: uuid.UUID | None = None

    def __post_init__(self) -> None:
        """Validate TEI revision metadata."""
        _validate_non_empty_text(self.tei_xml, "tei_xml")
        _require_positive_integer(self.tei_revision, "tei_revision")
        _validate_optional_text(
            self.tei_content_hash,
            "tei_content_hash",
        )


@dc.dataclass(frozen=True, slots=True)
class EpisodeTeiUpdate:
    """Optimistic TEI update request for a canonical episode."""

    tei_xml: str
    qa_status: QaStatus
    last_generation_run_id: uuid.UUID
    expected_revision: int
    updated_at: dt.datetime

    def __post_init__(self) -> None:
        """Validate optimistic TEI update invariants."""
        _validate_non_empty_text(self.tei_xml, "tei_xml")
        _require_value(self.qa_status, "qa_status")
        _require_value(self.last_generation_run_id, "last_generation_run_id")
        _require_positive_integer(self.expected_revision, "expected_revision")


@dc.dataclass(frozen=True, slots=True)
class ApprovalEvent:
    """Approval state transitions for canonical episodes."""

    id: uuid.UUID
    episode_id: uuid.UUID
    actor: str | None
    from_state: ApprovalState | None
    to_state: ApprovalState
    note: str | None
    payload: JsonMapping
    created_at: dt.datetime
