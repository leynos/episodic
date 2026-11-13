"""Verify every reference-resource mapper reaches the configured emitter."""

import asyncio
import dataclasses as dc
import typing as typ
from unittest import mock

import pytest
from falcon import testing

import episodic.api.app as api_app
import episodic.api.errors as api_errors
from episodic.api import ApiDependencies, create_app
from episodic.api.resources import reference_bindings, reference_documents
from episodic.canonical.reference_documents import ReferenceDocumentError

if typ.TYPE_CHECKING:
    import types

    from tests.fixtures.api_errors import EmptyUnitOfWorkFactory, SpyLogger

_PROFILE_ID = "00000000-0000-0000-0000-000000000007"
_DOCUMENT_ID = "00000000-0000-0000-0000-000000000008"
_REVISION_ID = "00000000-0000-0000-0000-000000000009"
_BINDING_ID = "00000000-0000-0000-0000-000000000010"
_TARGET_ID = "00000000-0000-0000-0000-000000000011"
_CREDENTIAL = "reference-route-secret-marker"


@dc.dataclass(frozen=True, slots=True)
class _ReferenceRouteCase:
    """Describe one reference-resource route and its failing service seam."""

    resource_module: types.ModuleType
    service_name: str
    path: str
    method: str = "GET"
    payload: dict[str, object] | None = None
    expected_context: str = "reference-document"


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(
            _ReferenceRouteCase(
                reference_documents,
                "list_reference_documents_paged",
                f"/v1/series-profiles/{_PROFILE_ID}/reference-documents",
            ),
            id="document-list",
        ),
        pytest.param(
            _ReferenceRouteCase(
                reference_documents,
                "get_reference_document",
                f"/v1/series-profiles/{_PROFILE_ID}/reference-documents/{_DOCUMENT_ID}",
            ),
            id="document-fetch",
        ),
        pytest.param(
            _ReferenceRouteCase(
                reference_documents,
                "create_reference_document",
                f"/v1/series-profiles/{_PROFILE_ID}/reference-documents",
                method="POST",
                payload={
                    "kind": "transcript",
                    "lifecycle_state": "active",
                    "metadata": {},
                },
            ),
            id="document-create",
        ),
        pytest.param(
            _ReferenceRouteCase(
                reference_documents,
                "update_reference_document",
                f"/v1/series-profiles/{_PROFILE_ID}/reference-documents/{_DOCUMENT_ID}",
                method="PATCH",
                payload={
                    "lifecycle_state": "active",
                    "metadata": {},
                    "expected_lock_version": 1,
                },
            ),
            id="document-update",
        ),
        pytest.param(
            _ReferenceRouteCase(
                reference_documents,
                "list_reference_document_revisions_paged",
                (
                    f"/v1/series-profiles/{_PROFILE_ID}/reference-documents/"
                    f"{_DOCUMENT_ID}/revisions"
                ),
            ),
            id="revision-list",
        ),
        pytest.param(
            _ReferenceRouteCase(
                reference_documents,
                "create_reference_document_revision",
                (
                    f"/v1/series-profiles/{_PROFILE_ID}/reference-documents/"
                    f"{_DOCUMENT_ID}/revisions"
                ),
                method="POST",
                payload={"content": {}, "content_hash": "sha256:example"},
            ),
            id="revision-create",
        ),
        pytest.param(
            _ReferenceRouteCase(
                reference_documents,
                "get_reference_document_revision",
                f"/v1/reference-document-revisions/{_REVISION_ID}",
            ),
            id="revision-fetch",
        ),
        pytest.param(
            _ReferenceRouteCase(
                reference_bindings,
                "list_reference_bindings_paged",
                f"/v1/reference-bindings?target_kind=series_profile&target_id={_TARGET_ID}",
                expected_context="reference-binding",
            ),
            id="binding-list",
        ),
        pytest.param(
            _ReferenceRouteCase(
                reference_bindings,
                "get_reference_binding",
                f"/v1/reference-bindings/{_BINDING_ID}",
                expected_context="reference-binding",
            ),
            id="binding-fetch",
        ),
        pytest.param(
            _ReferenceRouteCase(
                reference_bindings,
                "create_reference_binding",
                "/v1/reference-bindings",
                method="POST",
                payload={
                    "reference_document_revision_id": _REVISION_ID,
                    "target_kind": "series_profile",
                    "series_profile_id": _PROFILE_ID,
                },
                expected_context="reference-binding",
            ),
            id="binding-create",
        ),
    ],
)
def test_reference_routes_use_the_configured_error_emitter(
    case: _ReferenceRouteCase,
    spy_logger: SpyLogger,
    empty_uow_factory: EmptyUnitOfWorkFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reference reads, revisions and writes emit through the app dependency."""

    async def fail_service(*_args: object, **_kwargs: object) -> typ.NoReturn:
        """Raise an unmapped reference error from the selected service."""
        await asyncio.sleep(0)
        raise ReferenceDocumentError("Reference failure: " + _CREDENTIAL)

    default_logger = mock.Mock()
    monkeypatch.setattr(case.resource_module, case.service_name, fail_service)
    monkeypatch.setattr(api_app, "log_error", default_logger)
    monkeypatch.setattr(api_errors, "log_error", default_logger)
    client = testing.TestClient(
        create_app(
            ApiDependencies(
                uow_factory=empty_uow_factory,
                unmapped_error_emitter=spy_logger,
            )
        )
    )

    request_function = getattr(client, f"simulate_{case.method.lower()}")
    if case.payload is None:
        response = request_function(case.path)
    else:
        response = request_function(case.path, json=case.payload)

    assert response.status_code == 500, "unmapped reference errors must return HTTP 500"
    assert response.json == {
        "code": "internal_error",
        "message": f"Unexpected {case.expected_context} error.",
        "details": {},
    }, "reference routes must expose the generic internal-error envelope"
    assert len(spy_logger.calls) == 1, "the configured emitter must receive one record"
    assert spy_logger.calls[0][0] == "ERROR", "unmapped failures must use ERROR level"
    assert _CREDENTIAL not in spy_logger.calls[0][1], "logs must redact source values"
    assert default_logger.call_count == 0, "route errors must use the injected emitter"
