"""Behavioural tests for source-intake upload and attachment workflows."""

from __future__ import annotations

import typing as typ

from pytest_bdd import given, parsers, scenario, then, when

from tests.steps.source_intake_support import (
    SourceIntakeContext,
    attach_missing_upload,
    attach_pending_upload,
    attach_to_missing_job,
    attach_unknown_source_discriminator,
    list_attached_sources,
    run_intake_workflow,
    upload_oversized_source,
    upload_unsupported_content_type,
)

if typ.TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@scenario(
    "../features/source_intake.feature",
    "Editorial team uploads and attaches source material",
)
def test_source_intake_behaviour() -> None:
    """Run source-intake API scenario."""


@scenario("../features/source_intake.feature", "Upload content type is rejected")
def test_source_intake_rejects_content_type() -> None:
    """Run source-intake unsupported-content-type scenario."""


@scenario("../features/source_intake.feature", "Upload payload is too large")
def test_source_intake_rejects_oversized_payload() -> None:
    """Run source-intake oversized-payload scenario."""


@scenario(
    "../features/source_intake.feature",
    "Source attachment discriminator is invalid",
)
def test_source_intake_rejects_invalid_source_discriminator() -> None:
    """Run source-intake invalid-source-discriminator scenario."""


@scenario(
    "../features/source_intake.feature",
    "Source attachment references a missing job",
)
def test_source_intake_reports_missing_job() -> None:
    """Run source-intake missing-job scenario."""


@scenario(
    "../features/source_intake.feature",
    "Source attachment references a missing upload",
)
def test_source_intake_reports_missing_upload() -> None:
    """Run source-intake missing-upload scenario."""


@scenario(
    "../features/source_intake.feature",
    "Source attachment references an upload that is not ready",
)
def test_source_intake_reports_not_ready_upload() -> None:
    """Run source-intake not-ready-upload scenario."""


@scenario(
    "../features/source_intake.feature", "Editorial team lists attached source material"
)
def test_source_intake_lists_sources() -> None:
    """Run source-intake source-list scenario."""


@given("source-intake API fixtures exist", target_fixture="context")
def source_intake_fixtures() -> SourceIntakeContext:
    """Create an empty context for the source-intake API scenario."""
    return SourceIntakeContext()


@when("an editor uploads source material and attaches it to a new ingestion job")
def upload_and_attach_source(
    context: SourceIntakeContext,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """Exercise the upload, job creation, source attachment, and poll flow."""
    run_intake_workflow(context, session_factory, tmp_path)


@when("an editor uploads source material with an unsupported content type")
def upload_unsupported_source(
    context: SourceIntakeContext,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """Upload source material whose declared content type is not allowlisted."""
    upload_unsupported_content_type(context, session_factory, tmp_path)


@when("an editor uploads source material larger than the configured cap")
def upload_oversized_material(
    context: SourceIntakeContext,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """Upload source material that exceeds the configured byte cap."""
    upload_oversized_source(context, session_factory, tmp_path)


@when("an editor attaches source material with an unknown discriminator")
def attach_unknown_discriminator(
    context: SourceIntakeContext,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """Attach source material with an invalid ``type`` discriminator."""
    attach_unknown_source_discriminator(context, session_factory, tmp_path)


@when("an editor attaches source material to a missing ingestion job")
def attach_source_to_missing_job(
    context: SourceIntakeContext,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """Attach source material to an ingestion job that does not exist."""
    attach_to_missing_job(context, session_factory, tmp_path)


@when("an editor attaches a missing upload to a new ingestion job")
def attach_unknown_upload(
    context: SourceIntakeContext,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """Attach an unknown upload to a known ingestion job."""
    attach_missing_upload(context, session_factory, tmp_path)


@when("an editor attaches a pending upload to a new ingestion job")
def attach_upload_that_is_pending(
    context: SourceIntakeContext,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """Attach a pending upload to a known ingestion job."""
    attach_pending_upload(context, session_factory, tmp_path)


@when("an editor lists source material attached to a new ingestion job")
def list_sources(
    context: SourceIntakeContext,
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """List source material attached to a new ingestion job."""
    list_attached_sources(context, session_factory, tmp_path)


@then("the ingestion job is ready for generation")
def assert_job_ready(context: SourceIntakeContext) -> None:
    """Verify the source attachment transitioned the intake state."""
    assert context.upload is not None
    assert context.job is not None
    assert context.source is not None
    assert context.status is not None
    assert context.job["intake_state"] == "awaiting_sources"
    assert context.source["upload_id"] == context.upload["id"]
    assert context.status["intake_state"] == "ready_for_generation"


@then("repeated upload requests replay the stored response")
def assert_upload_replay(context: SourceIntakeContext) -> None:
    """Verify an identical idempotency key/body pair returns the stored upload."""
    assert context.upload is not None
    assert context.upload_replay == context.upload


@then("changed upload bodies with the same idempotency key conflict")
def assert_upload_conflict(context: SourceIntakeContext) -> None:
    """Verify a reused idempotency key with a different body returns 409."""
    assert context.conflict_status == 409
    assert context.conflict is not None
    assert context.conflict["code"] == "idempotency_conflict"


@then(parsers.parse('the source-intake API rejects the request with "{error_code}"'))
def assert_source_intake_error(
    context: SourceIntakeContext,
    error_code: str,
) -> None:
    """Verify the source-intake API returned a documented error envelope."""
    assert context.error_status is not None
    assert context.error_status >= 400
    assert context.error_code == error_code


@then("the source-intake API returns the attached source material")
def assert_source_list(context: SourceIntakeContext) -> None:
    """Verify the attached source appears in the source-list endpoint."""
    assert context.upload is not None
    assert context.source_list is not None
    assert context.source_list["total"] == 1
    items = typ.cast("list[dict[str, object]]", context.source_list["items"])
    assert items[0]["upload_id"] == context.upload["id"]
