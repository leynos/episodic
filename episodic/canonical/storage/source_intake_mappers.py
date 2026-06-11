"""Record mappers for source-intake persistence."""

import copy

from episodic.canonical.idempotency import IdempotencyRecord
from episodic.canonical.ingestion_sources import IngestionJobSource
from episodic.canonical.uploads import Upload

from .source_intake_models import (
    IdempotencyRecordModel,
    IngestionJobSourceRecord,
    UploadRecord,
)

_ANONYMOUS_PRINCIPAL = ""


def _principal_to_record(value: str | None) -> str:
    """Normalise optional principals for database uniqueness."""
    return _ANONYMOUS_PRINCIPAL if value is None else value


def _principal_from_record(value: str) -> str | None:
    """Map the database anonymous-principal sentinel back to the domain."""
    return None if value == _ANONYMOUS_PRINCIPAL else value


def _metadata_payload_to_domain[T](record_metadata_payload: T) -> T:
    """Deep-copy a record metadata_payload field into the domain metadata field."""
    return copy.deepcopy(record_metadata_payload)


def _metadata_domain_to_payload[T](domain_metadata: T) -> T:
    """Deep-copy a domain metadata field into the record metadata_payload field."""
    return copy.deepcopy(domain_metadata)


def _upload_from_record(record: UploadRecord) -> Upload:
    """Map an upload record to a domain entity."""
    return Upload(
        id=record.id,
        owner_principal_id=record.owner_principal_id,
        content_type=record.content_type,
        declared_size=record.declared_size,
        actual_size=record.actual_size,
        declared_sha256=record.declared_sha256,
        content_hash=record.content_hash,
        storage_key=record.storage_key,
        state=record.state,
        metadata=_metadata_payload_to_domain(record.metadata_payload),
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _upload_to_record(upload: Upload) -> UploadRecord:
    """Map an upload domain entity to a record."""
    return UploadRecord(
        id=upload.id,
        owner_principal_id=upload.owner_principal_id,
        content_type=upload.content_type,
        declared_size=upload.declared_size,
        actual_size=upload.actual_size,
        declared_sha256=upload.declared_sha256,
        content_hash=upload.content_hash,
        storage_key=upload.storage_key,
        state=upload.state,
        metadata_payload=_metadata_domain_to_payload(upload.metadata),
        created_at=upload.created_at,
        updated_at=upload.updated_at,
    )


def _ingestion_job_source_from_record(
    record: IngestionJobSourceRecord,
) -> IngestionJobSource:
    """Map a source-attachment record to a domain entity."""
    return IngestionJobSource(
        id=record.id,
        ingestion_job_id=record.ingestion_job_id,
        attachment_kind=record.attachment_kind,
        upload_id=record.upload_id,
        source_uri=record.source_uri,
        source_type=record.source_type,
        weight=record.weight,
        metadata=_metadata_payload_to_domain(record.metadata_payload),
        created_at=record.created_at,
    )


def _ingestion_job_source_to_record(
    source: IngestionJobSource,
) -> IngestionJobSourceRecord:
    """Map a source-attachment domain entity to a record."""
    return IngestionJobSourceRecord(
        id=source.id,
        ingestion_job_id=source.ingestion_job_id,
        attachment_kind=source.attachment_kind,
        upload_id=source.upload_id,
        source_uri=source.source_uri,
        source_type=source.source_type,
        weight=source.weight,
        metadata_payload=_metadata_domain_to_payload(source.metadata),
        created_at=source.created_at,
    )


def _idempotency_record_from_record(
    record: IdempotencyRecordModel,
) -> IdempotencyRecord:
    """Map an idempotency record to a domain entity."""
    return IdempotencyRecord(
        id=record.id,
        principal_id=_principal_from_record(record.principal_id),
        operation=record.operation,
        idempotency_key=record.idempotency_key,
        body_hash=record.body_hash,
        state=record.state,
        serialised_outcome=record.serialised_outcome,
        expires_at=record.expires_at,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )
