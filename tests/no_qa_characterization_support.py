"""Characterization payloads for the no-QA generation-slice snapshots.

The payload records the persisted run and episode rows, the event stream, every
metrics emission, and the execution span attributes in a deterministic form.
Identifiers are normalized through :mod:`tests.snapshot_redaction`, and a
latency observation records its name and labels but not its elapsed value,
which is wall-clock dependent.
"""

import dataclasses as dc
import typing as typ

from tests.generation_run_launcher_support import valid_tei
from tests.snapshot_redaction import (
    redact_snapshot_hashes,
    redact_snapshot_uuids,
)

if typ.TYPE_CHECKING:
    from episodic.canonical.domain import (
        CanonicalEpisode,
        GenerationEvent,
        GenerationRun,
    )
    from episodic.observability import RecordingTracer
    from tests.generation_run_launcher_observation_support import RecordingMetrics


@dc.dataclass(frozen=True, slots=True)
class Findings:
    """Persisted and observed artefacts of one characterization case."""

    run: GenerationRun
    events: tuple[GenerationEvent, ...]
    episode: CanonicalEpisode
    metrics: RecordingMetrics
    tracer: RecordingTracer


def _redact(value: object) -> object:
    """Normalize identifiers and content hashes in one recorded value."""
    return redact_snapshot_hashes(redact_snapshot_uuids(value))


def payload(findings: Findings) -> dict[str, object]:
    """Build the deterministic snapshot payload for one case."""
    run = findings.run
    metric_rows = [
        {
            "kind": observation.kind,
            "name": observation.name,
            "labels": observation.labels,
            "value": (
                "<elapsed_ms>" if observation.value is None else observation.value
            ),
        }
        for observation in findings.metrics.observations
    ]
    span_rows = [
        {
            "name": span.name,
            "attributes": _redact(span.attributes),
            "is_completed": span.is_completed,
        }
        for span in findings.tracer.spans
    ]
    return {
        "events": [
            {"kind": event.kind, "payload": _redact(event.payload)}
            for event in findings.events
        ],
        "run": {
            "status": run.status.value,
            "current_node": run.current_node,
            "error_category": run.error_category,
            "error_message": _redact(run.error_message),
            "quality_mode": run.quality_mode.value,
            "qa_status": None if run.qa_status is None else run.qa_status.value,
            "skip_qa_rationale": run.skip_qa_rationale,
            "has_started_at": run.started_at is not None,
            "has_ended_at": run.ended_at is not None,
        },
        "episode": {
            "tei_revision": findings.episode.tei_revision,
            "tei_content_hash": _redact(findings.episode.tei_content_hash),
            "qa_status": (
                None
                if findings.episode.qa_status is None
                else findings.episode.qa_status.value
            ),
            "has_generated_draft": findings.episode.tei_xml == valid_tei(),
        },
        "metrics": metric_rows,
        "spans": span_rows,
    }
