"""Record-to-domain mappings for generation runs and their events."""

from episodic.canonical.domain import GenerationEvent, GenerationRun
from episodic.canonical.generation_run_ports import event_seq

from .generation_run_models import GenerationEventRecord, GenerationRunRecord

_ANONYMOUS_IDEMPOTENCY_PRINCIPAL = "__anonymous__"


def normalise_idempotency_principal(principal_id: str | None) -> str:
    """Return the persisted principal scope for an idempotency key."""
    return principal_id or _ANONYMOUS_IDEMPOTENCY_PRINCIPAL


def run_from_record(record: GenerationRunRecord) -> GenerationRun:
    """Map a generation-run record to a domain entity."""
    return GenerationRun(
        id=record.id,
        episode_id=record.episode_id,
        source_bundle_id=record.source_bundle_id,
        actor=record.actor,
        status=record.status,
        current_node=record.current_node,
        budget_snapshot=record.budget_snapshot,
        configuration=record.configuration,
        created_at=record.created_at,
        updated_at=record.updated_at,
        started_at=record.started_at,
        ended_at=record.ended_at,
        error_message=record.error_message,
        error_category=record.error_category,
        quality_mode=record.quality_mode,
        qa_status=record.qa_status,
        skip_qa_rationale=record.skip_qa_rationale,
    )


def run_to_record(
    run: GenerationRun,
    *,
    idempotency_key: str | None,
    idempotency_principal_id: str | None,
) -> GenerationRunRecord:
    """Map a generation-run domain entity to a SQLAlchemy record."""
    return GenerationRunRecord(
        id=run.id,
        episode_id=run.episode_id,
        source_bundle_id=run.source_bundle_id,
        actor=run.actor,
        status=run.status,
        current_node=run.current_node,
        budget_snapshot=run.budget_snapshot,
        configuration=run.configuration,
        quality_mode=run.quality_mode,
        qa_status=run.qa_status,
        skip_qa_rationale=run.skip_qa_rationale,
        idempotency_principal_id=normalise_idempotency_principal(
            idempotency_principal_id
        ),
        idempotency_key=idempotency_key,
        error_message=run.error_message,
        error_category=run.error_category,
        lease_expires_at=None,
        started_at=run.started_at,
        ended_at=run.ended_at,
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


def event_from_record(record: GenerationEventRecord) -> GenerationEvent:
    """Map an event record to a domain event."""
    return GenerationEvent(
        id=record.id,
        generation_run_id=record.generation_run_id,
        seq=event_seq(record.seq),
        kind=record.kind,
        payload=record.payload,
        occurred_at=record.occurred_at,
        created_at=record.created_at,
    )
