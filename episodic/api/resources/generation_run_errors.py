"""Canonical HTTP error responses for generation-run resources."""

import typing as typ

import falcon

from episodic.api.errors import http_error

if typ.TYPE_CHECKING:
    import uuid


def generation_overloaded() -> falcon.HTTPServiceUnavailable:
    """Build the stable response for rejected in-process launch admission."""
    return typ.cast(
        "falcon.HTTPServiceUnavailable",
        http_error(
            falcon.HTTPServiceUnavailable(
                description="Generation capacity is temporarily exhausted."
            ),
            code="generation_overloaded",
        ),
    )


def run_not_found(run_id: uuid.UUID) -> falcon.HTTPNotFound:
    """Build the non-disclosing response for an inaccessible generation run."""
    return typ.cast(
        "falcon.HTTPNotFound",
        http_error(
            falcon.HTTPNotFound(description=f"Generation run not found: {run_id}."),
            code="generation_run_not_found",
            details={"run_id": str(run_id)},
        ),
    )


def ingestion_job_not_found(ingestion_job_id: uuid.UUID) -> falcon.HTTPNotFound:
    """Build the non-disclosing response for an inaccessible ingestion job."""
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


def generation_input_error(message: str) -> falcon.HTTPUnprocessableEntity:
    """Build the standard response for invalid generation source material."""
    return typ.cast(
        "falcon.HTTPUnprocessableEntity",
        http_error(
            falcon.HTTPUnprocessableEntity(description=message),
            code="generation_input_invalid",
        ),
    )
