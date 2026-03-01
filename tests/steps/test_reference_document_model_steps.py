"""Behavioural tests for the reusable reference-document model."""

from __future__ import annotations

import datetime as dt
import typing as typ
import uuid

import pytest
from pytest_bdd import given, scenario, then, when

from episodic.canonical.domain import (
    ReferenceBinding,
    ReferenceBindingTargetKind,
    ReferenceDocument,
    ReferenceDocumentKind,
    ReferenceDocumentLifecycleState,
    ReferenceDocumentRevision,
)
from episodic.canonical.storage import SqlAlchemyUnitOfWork

if typ.TYPE_CHECKING:
    import asyncio
    import collections.abc as cabc

    from falcon import testing
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _run_async_step(
    runner: asyncio.Runner,
    step_fn: cabc.Callable[[], typ.Coroutine[object, object, None]],
) -> None:
    """Execute an async BDD step via the provided runner."""
    runner.run(step_fn())


class ReferenceDocumentContext(typ.TypedDict, total=False):
    """Shared scenario context for reference-document BDD steps."""

    profile_id: str
    template_id: str
    brief_payload: dict[str, object]


@scenario(
    "../features/reference_document_model.feature",
    "Structured brief includes bound host and guest reference documents",
)
def test_reference_document_model_alignment() -> None:
    """Run reusable reference-document alignment scenario."""


@pytest.fixture
def context() -> ReferenceDocumentContext:
    """Share state between reference-document BDD steps."""
    return typ.cast("ReferenceDocumentContext", {})


@given("a series profile and episode template exist")
def create_profile_and_template(
    canonical_api_client: testing.TestClient,
    context: ReferenceDocumentContext,
) -> None:
    """Create profile/template entities used for binding checks."""
    profile_response = canonical_api_client.simulate_post(
        "/series-profiles",
        json={
            "slug": "bdd-ref-profile",
            "title": "BDD Reference Profile",
            "description": "Series profile for reference model checks.",
            "configuration": {"tone": "direct"},
            "actor": "bdd@example.com",
            "note": "Create profile",
        },
    )
    assert profile_response.status_code == 201
    profile_id = typ.cast("str", profile_response.json["id"])

    template_response = canonical_api_client.simulate_post(
        "/episode-templates",
        json={
            "series_profile_id": profile_id,
            "slug": "bdd-ref-template",
            "title": "BDD Reference Template",
            "description": "Template for reference model checks.",
            "structure": {"segments": ["intro", "discussion", "outro"]},
            "actor": "bdd@example.com",
            "note": "Create template",
        },
    )
    assert template_response.status_code == 201

    context["profile_id"] = profile_id
    context["template_id"] = typ.cast("str", template_response.json["id"])


def _build_reference_document_set(
    *,
    profile_uuid: uuid.UUID,
    template_uuid: uuid.UUID,
    kind: ReferenceDocumentKind,
    target_kind: ReferenceBindingTargetKind,
    name: str,
    bio: str,
    content_hash: str,
    now: dt.datetime,
) -> tuple[ReferenceDocument, ReferenceDocumentRevision, ReferenceBinding]:
    """Build a reusable reference document, revision, and binding tuple."""
    change_notes = {
        ReferenceDocumentKind.HOST_PROFILE: "Create host revision",
        ReferenceDocumentKind.GUEST_PROFILE: "Create guest revision",
    }
    document = ReferenceDocument(
        id=uuid.uuid4(),
        owner_series_profile_id=profile_uuid,
        kind=kind,
        lifecycle_state=ReferenceDocumentLifecycleState.ACTIVE,
        metadata={"name": name},
        created_at=now,
        updated_at=now,
    )
    revision = ReferenceDocumentRevision(
        id=uuid.uuid4(),
        reference_document_id=document.id,
        content={"bio": bio},
        content_hash=content_hash,
        author="bdd@example.com",
        change_note=change_notes[kind],
        created_at=now,
    )
    binding = ReferenceBinding(
        id=uuid.uuid4(),
        reference_document_revision_id=revision.id,
        target_kind=target_kind,
        series_profile_id=(
            profile_uuid
            if target_kind is ReferenceBindingTargetKind.SERIES_PROFILE
            else None
        ),
        episode_template_id=(
            template_uuid
            if target_kind is ReferenceBindingTargetKind.EPISODE_TEMPLATE
            else None
        ),
        ingestion_job_id=None,
        effective_from_episode_id=None,
        created_at=now,
    )
    return document, revision, binding


@given("host and guest reference revisions are bound to the profile and template")
def bind_reference_revisions(
    _function_scoped_runner: asyncio.Runner,
    session_factory: async_sessionmaker[AsyncSession],
    context: ReferenceDocumentContext,
) -> None:
    """Persist reusable host/guest reference documents and bindings."""

    async def _bind() -> None:
        now = dt.datetime.now(dt.UTC)
        profile_uuid = uuid.UUID(context["profile_id"])
        template_uuid = uuid.UUID(context["template_id"])

        host_document, host_revision, host_binding = _build_reference_document_set(
            profile_uuid=profile_uuid,
            template_uuid=template_uuid,
            kind=ReferenceDocumentKind.HOST_PROFILE,
            target_kind=ReferenceBindingTargetKind.SERIES_PROFILE,
            name="Host One",
            bio="Host profile content",
            content_hash="hash-host-bdd",
            now=now,
        )

        guest_document, guest_revision, guest_binding = _build_reference_document_set(
            profile_uuid=profile_uuid,
            template_uuid=template_uuid,
            kind=ReferenceDocumentKind.GUEST_PROFILE,
            target_kind=ReferenceBindingTargetKind.EPISODE_TEMPLATE,
            name="Guest One",
            bio="Guest profile content",
            content_hash="hash-guest-bdd",
            now=now,
        )

        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            await uow.reference_documents.add(host_document)
            await uow.reference_document_revisions.add(host_revision)
            await uow.reference_documents.add(guest_document)
            await uow.reference_document_revisions.add(guest_revision)
            await uow.flush()
            await uow.reference_bindings.add(host_binding)
            await uow.reference_bindings.add(guest_binding)
            await uow.commit()

    _run_async_step(_function_scoped_runner, _bind)


@when("the structured brief is retrieved for the profile and template")
def retrieve_brief(
    canonical_api_client: testing.TestClient,
    context: ReferenceDocumentContext,
) -> None:
    """Retrieve structured brief payload via API."""
    response = canonical_api_client.simulate_get(
        f"/series-profiles/{context['profile_id']}/brief",
        params={"template_id": context["template_id"]},
    )
    assert response.status_code == 200
    context["brief_payload"] = typ.cast("dict[str, object]", response.json)


@then("the structured brief includes host and guest reference documents")
def assert_reference_documents(context: ReferenceDocumentContext) -> None:
    """Assert brief payload contains bound host/guest reference documents."""
    brief_payload = context["brief_payload"]
    documents = typ.cast(
        "list[dict[str, object]]", brief_payload["reference_documents"]
    )

    assert len(documents) == 2, (
        "Expected brief payload to include host and guest reference documents."
    )
    kinds = {typ.cast("str", item["kind"]) for item in documents}
    target_kinds = {typ.cast("str", item["target_kind"]) for item in documents}
    assert kinds == {"host_profile", "guest_profile"}
    assert target_kinds == {"series_profile", "episode_template"}
