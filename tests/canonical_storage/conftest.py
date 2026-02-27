"""Shared fixtures for canonical storage tests."""

from __future__ import annotations

import base64
import datetime as dt
import uuid
from compression import zstd

import pytest

from episodic.canonical.domain import (
    ApprovalState,
    CanonicalEpisode,
    EpisodeStatus,
    IngestionJob,
    IngestionStatus,
    SeriesProfile,
    SourceDocument,
    TeiHeader,
)

_COMPRESSION_THRESHOLD_BYTES = 1024


@pytest.fixture
def episode_fixture() -> tuple[
    SeriesProfile,
    TeiHeader,
    CanonicalEpisode,
    IngestionJob,
    SourceDocument,
]:
    """Return a set of related canonical entities."""
    now = dt.datetime.now(dt.UTC)
    series_id = uuid.uuid4()
    header_id = uuid.uuid4()
    episode_id = uuid.uuid4()
    job_id = uuid.uuid4()

    series = SeriesProfile(
        id=series_id,
        slug="nightshift",
        title="Nightshift",
        description="After-dark science news.",
        configuration={"tone": "calm"},
        created_at=now,
        updated_at=now,
    )
    header = TeiHeader(
        id=header_id,
        title="Nightshift Episode 1",
        payload={"file_desc": {"title": "Nightshift Episode 1"}},
        raw_xml="<TEI/>",
        created_at=now,
        updated_at=now,
    )
    episode = CanonicalEpisode(
        id=episode_id,
        series_profile_id=series_id,
        tei_header_id=header_id,
        title="Nightshift Episode 1",
        tei_xml="<TEI/>",
        status=EpisodeStatus.DRAFT,
        approval_state=ApprovalState.DRAFT,
        created_at=now,
        updated_at=now,
    )
    job = IngestionJob(
        id=job_id,
        series_profile_id=series_id,
        target_episode_id=episode_id,
        status=IngestionStatus.COMPLETED,
        requested_at=now,
        started_at=now,
        completed_at=now,
        error_message=None,
        created_at=now,
        updated_at=now,
    )
    source = SourceDocument(
        id=uuid.uuid4(),
        ingestion_job_id=job_id,
        canonical_episode_id=episode_id,
        source_type="web",
        source_uri="https://example.com",
        weight=0.75,
        content_hash="hash-1",
        metadata={"kind": "article"},
        created_at=now,
    )

    return (series, header, episode, job, source)


@pytest.fixture
def precompressed_tei_xml_payload() -> str:
    """Return deterministic TEI payload that remains below compression threshold."""
    seed_bytes = bytes(range(256))
    precompressed_body = base64.b64encode(zstd.compress(seed_bytes)).decode("ascii")
    payload = f"<TEI>{precompressed_body}</TEI>"
    if len(payload.encode("utf-8")) >= _COMPRESSION_THRESHOLD_BYTES:
        msg = "Expected test payload to remain below default compression threshold."
        raise ValueError(msg)
    return payload
