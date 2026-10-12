"""Unit tests for reusable reference-document domain models."""

import datetime as dt
import typing as typ
import uuid

import pytest

from episodic.canonical.domain import (
    ReferenceBinding,
    ReferenceBindingTargetKind,
    ReferenceDocument,
    ReferenceDocumentKind,
    ReferenceDocumentLifecycleState,
    ReferenceDocumentRevision,
)


def _build_reference_document(*, lock_version: int = 1) -> ReferenceDocument:
    """Build a reference document with a configurable lock version."""
    now = dt.datetime.now(dt.UTC)
    return ReferenceDocument(
        id=uuid.uuid4(),
        owner_series_profile_id=uuid.uuid4(),
        kind=ReferenceDocumentKind.HOST_PROFILE,
        lifecycle_state=ReferenceDocumentLifecycleState.ACTIVE,
        metadata={},
        created_at=now,
        updated_at=now,
        lock_version=lock_version,
    )


def _build_reference_document_revision(
    *,
    content_hash: str = "hash",
) -> ReferenceDocumentRevision:
    """Build a revision with a configurable content hash."""
    return ReferenceDocumentRevision(
        id=uuid.uuid4(),
        reference_document_id=uuid.uuid4(),
        content={},
        content_hash=content_hash,
        author="author@example.com",
        change_note="Regression test revision.",
        created_at=dt.datetime.now(dt.UTC),
    )


def _build_reference_binding(
    *,
    target_kind: ReferenceBindingTargetKind,
    **kwargs: uuid.UUID | None,
) -> ReferenceBinding:
    """Build a reference binding for tests."""
    now = dt.datetime.now(dt.UTC)
    return ReferenceBinding(
        id=uuid.uuid4(),
        reference_document_revision_id=uuid.uuid4(),
        target_kind=target_kind,
        series_profile_id=kwargs.get("series_profile_id"),
        episode_template_id=kwargs.get("episode_template_id"),
        ingestion_job_id=kwargs.get("ingestion_job_id"),
        effective_from_episode_id=kwargs.get("effective_from_episode_id"),
        created_at=now,
    )


def test_reference_document_kind_supports_host_and_guest_profiles() -> None:
    """Host and guest profile kinds should be part of the reusable model."""
    assert ReferenceDocumentKind.HOST_PROFILE.value == "host_profile", (
        "expected host_profile for ReferenceDocumentKind.HOST_PROFILE"
    )
    assert ReferenceDocumentKind.GUEST_PROFILE.value == "guest_profile", (
        "expected guest_profile for ReferenceDocumentKind.GUEST_PROFILE"
    )


@pytest.mark.parametrize(
    "lock_version",
    [
        pytest.param(True, id="true-is-not-an-integer"),
        pytest.param(False, id="false-is-not-an-integer"),
        pytest.param(0, id="zero"),
        pytest.param(-1, id="negative"),
        pytest.param(1.5, id="float"),
        pytest.param("1", id="string"),
        pytest.param(None, id="none"),
        pytest.param(object(), id="object"),
    ],
)
def test_reference_document_rejects_invalid_lock_version(
    lock_version: object,
) -> None:
    """The dataclass constructor rejects non-positive exact integers."""
    with pytest.raises(
        ValueError,
        match=r"^lock_version must be a positive integer\.$",
    ) as raised:
        _build_reference_document(lock_version=typ.cast("int", lock_version))

    assert str(raised.value) == "lock_version must be a positive integer.", (
        f"unexpected lock_version validation message: {raised.value!s}."
    )


@pytest.mark.parametrize(
    "lock_version",
    [pytest.param(1, id="smallest-positive"), pytest.param(42, id="larger-positive")],
)
def test_reference_document_accepts_positive_lock_version(lock_version: int) -> None:
    """Positive integer lock versions survive construction unchanged."""
    assert _build_reference_document(lock_version=lock_version).lock_version == (
        lock_version
    ), f"expected lock_version {lock_version}, got a different value."


def test_reference_document_defaults_lock_version_to_one() -> None:
    """A newly constructed document starts at lock version one."""
    now = dt.datetime.now(dt.UTC)
    document = ReferenceDocument(
        id=uuid.uuid4(),
        owner_series_profile_id=uuid.uuid4(),
        kind=ReferenceDocumentKind.HOST_PROFILE,
        lifecycle_state=ReferenceDocumentLifecycleState.ACTIVE,
        metadata={},
        created_at=now,
        updated_at=now,
    )

    assert document.lock_version == 1, "expected the default lock_version to be one."


@pytest.mark.parametrize(
    "content_hash",
    [
        pytest.param(object(), id="object"),
        pytest.param(None, id="none"),
        pytest.param(123, id="integer"),
        pytest.param(True, id="boolean"),
        pytest.param([], id="list"),
    ],
)
def test_reference_document_revision_rejects_non_string_content_hash(
    content_hash: object,
) -> None:
    """The revision constructor requires a string content hash."""
    with pytest.raises(TypeError) as raised:
        _build_reference_document_revision(content_hash=typ.cast("str", content_hash))

    assert str(raised.value) == "content_hash must be a string.", (
        f"unexpected content_hash type message: {raised.value!s}."
    )


@pytest.mark.parametrize(
    "content_hash",
    [pytest.param("", id="empty"), pytest.param(" \t\n", id="whitespace-only")],
)
def test_reference_document_revision_rejects_blank_content_hash(
    content_hash: str,
) -> None:
    """Empty and whitespace-only hashes fail at the dataclass boundary."""
    with pytest.raises(
        ValueError,
        match=r"^content_hash must be a non-empty string\.$",
    ) as raised:
        _build_reference_document_revision(content_hash=content_hash)

    assert str(raised.value) == "content_hash must be a non-empty string.", (
        f"unexpected blank content_hash message: {raised.value!s}."
    )


def test_reference_document_revision_accepts_non_empty_content_hash() -> None:
    """A valid content hash survives revision construction unchanged."""
    revision = _build_reference_document_revision(content_hash="sha256:abc123")

    assert revision.content_hash == "sha256:abc123", (
        "expected the valid hash to survive construction, got "
        f"{revision.content_hash!r}."
    )


def test_reference_binding_rejects_missing_target_identifier() -> None:
    """A binding should require exactly one concrete target identifier."""
    with pytest.raises(ValueError, match="exactly one target identifier"):
        _build_reference_binding(
            target_kind=ReferenceBindingTargetKind.SERIES_PROFILE,
        )


def test_reference_binding_rejects_target_kind_mismatch() -> None:
    """Target kind must match the populated target identifier field."""
    with pytest.raises(ValueError, match="does not match populated target"):
        _build_reference_binding(
            target_kind=ReferenceBindingTargetKind.SERIES_PROFILE,
            episode_template_id=uuid.uuid4(),
        )


def test_reference_binding_rejects_effective_from_for_non_series_target() -> None:
    """effective_from_episode_id should be series-target specific."""
    with pytest.raises(ValueError, match="effective_from_episode_id"):
        _build_reference_binding(
            target_kind=ReferenceBindingTargetKind.EPISODE_TEMPLATE,
            episode_template_id=uuid.uuid4(),
            effective_from_episode_id=uuid.uuid4(),
        )


def test_reference_binding_accepts_series_target_with_effective_from_episode() -> None:
    """Series-target bindings may include effective_from_episode_id."""
    series_profile_id = uuid.uuid4()
    effective_from_episode_id = uuid.uuid4()
    binding = _build_reference_binding(
        target_kind=ReferenceBindingTargetKind.SERIES_PROFILE,
        series_profile_id=series_profile_id,
        effective_from_episode_id=effective_from_episode_id,
    )

    assert binding.series_profile_id == series_profile_id, (
        "expected series_profile_id to match the provided UUID"
    )
    assert binding.effective_from_episode_id == effective_from_episode_id, (
        "expected effective_from_episode_id to match the provided UUID"
    )


def test_reference_binding_accepts_ingestion_job_target() -> None:
    """Non-series bindings are accepted without effective_from_episode_id."""
    ingestion_job_id = uuid.uuid4()

    binding = _build_reference_binding(
        target_kind=ReferenceBindingTargetKind.INGESTION_JOB,
        ingestion_job_id=ingestion_job_id,
        effective_from_episode_id=None,
    )

    assert binding.target_kind is ReferenceBindingTargetKind.INGESTION_JOB, (
        "expected target_kind to remain INGESTION_JOB"
    )
    assert binding.ingestion_job_id == ingestion_job_id, (
        "expected ingestion_job_id to match the provided UUID"
    )
    assert binding.effective_from_episode_id is None, (
        "expected effective_from_episode_id to remain None for ingestion targets"
    )


def test_reference_document_accepts_series_aligned_host_profile() -> None:
    """Reference documents should represent series-aligned host profiles."""
    now = dt.datetime.now(dt.UTC)
    document = ReferenceDocument(
        id=uuid.uuid4(),
        owner_series_profile_id=uuid.uuid4(),
        kind=ReferenceDocumentKind.HOST_PROFILE,
        lifecycle_state=ReferenceDocumentLifecycleState.ACTIVE,
        metadata={"display_name": "Host A"},
        created_at=now,
        updated_at=now,
    )

    assert document.kind is ReferenceDocumentKind.HOST_PROFILE, (
        "expected document.kind to be HOST_PROFILE"
    )
    assert document.lifecycle_state is ReferenceDocumentLifecycleState.ACTIVE, (
        "expected document.lifecycle_state to be ACTIVE"
    )
