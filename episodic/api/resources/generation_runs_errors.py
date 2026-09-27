"""Error-response builders shared by generation-run HTTP resources."""

import typing as typ

import falcon

from episodic.api.errors import http_error

if typ.TYPE_CHECKING:
    import uuid

    from episodic.canonical.domain import IngestionJob

_RETRY_AFTER = "1"


def _generation_overloaded() -> falcon.HTTPServiceUnavailable:
    """Build the stable response for a rejected in-process launch."""
    return typ.cast(
        "falcon.HTTPServiceUnavailable",
        http_error(
            falcon.HTTPServiceUnavailable(
                description="Generation capacity is temporarily exhausted."
            ),
            code="generation_overloaded",
        ),
    )


def _run_not_found(run_id: uuid.UUID) -> falcon.HTTPNotFound:
    return typ.cast(
        "falcon.HTTPNotFound",
        http_error(
            falcon.HTTPNotFound(description=f"Generation run not found: {run_id}."),
            code="generation_run_not_found",
            details={"run_id": str(run_id)},
        ),
    )


def _ingestion_job_not_found(ingestion_job_id: uuid.UUID) -> falcon.HTTPNotFound:
    """Build a non-disclosing response for an inaccessible ingestion job."""
    return typ.cast(
        "falcon.HTTPNotFound",
        http_error(
            falcon.HTTPNotFound(
                description=f"Ingestion job not found: {ingestion_job_id}."
            ),
            code="ingestion_job_not_found",
            details={"ingestion_job_id": str(ingestion_job_id)},
        ),
    )


def _owns_ingestion_job(job: IngestionJob, principal: str | None) -> bool:
    """Return whether the server-derived principal can use an ingestion job."""
    return principal is not None and job.owner_principal_id == principal


def _generation_input_error(message: str) -> falcon.HTTPUnprocessableEntity:
    return typ.cast(
        "falcon.HTTPUnprocessableEntity",
        http_error(
            falcon.HTTPUnprocessableEntity(description=message),
            code="generation_input_invalid",
        ),
    )
