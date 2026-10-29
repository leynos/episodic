"""Verify unmapped errors cross the Falcon API boundary safely."""

import asyncio
import dataclasses as dc
import typing as typ

import pytest
from falcon import testing

from episodic.api import ApiDependencies, create_app
from episodic.api.resources import reference_documents, series_profiles, source_intake
from episodic.canonical.profile_templates.types import ProfileTemplateError
from episodic.canonical.reference_documents.types import ReferenceDocumentError
from episodic.canonical.source_intake_errors import SourceIntakeError

if typ.TYPE_CHECKING:
    import types

    from tests.fixtures.api_errors import EmptyUnitOfWorkFactory, SpyLogger

_ENTITY_ID = "00000000-0000-0000-0000-000000000007"
_CREDENTIAL = "route-test-secret-marker"


@dc.dataclass(frozen=True, slots=True)
class _RouteCase:
    """Describe one API route that maps an unmapped domain error."""

    resource_module: types.ModuleType
    service_name: str
    exception: Exception
    path: str
    expected_message: str


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(
            _RouteCase(
                series_profiles,
                "get_entity_with_revision",
                ProfileTemplateError(
                    "Profile failure: " + _CREDENTIAL,
                    code=_CREDENTIAL,
                    entity_id=_CREDENTIAL,
                ),
                f"/v1/series-profiles/{_ENTITY_ID}",
                "Unexpected profile/template error.",
            ),
            id="profile-template",
        ),
        pytest.param(
            _RouteCase(
                reference_documents,
                "list_reference_documents_paged",
                ReferenceDocumentError("Reference failure: " + _CREDENTIAL),
                f"/v1/series-profiles/{_ENTITY_ID}/reference-documents",
                "Unexpected reference-document error.",
            ),
            id="reference-document",
        ),
        pytest.param(
            _RouteCase(
                source_intake,
                "get_upload",
                SourceIntakeError("Source-intake failure: " + _CREDENTIAL),
                f"/v1/uploads/{_ENTITY_ID}",
                "Unexpected source-intake error.",
            ),
            id="source-intake",
        ),
    ],
)
def test_unmapped_errors_return_generic_http_500_envelopes(
    case: _RouteCase,
    spy_logger: SpyLogger,
    empty_uow_factory: EmptyUnitOfWorkFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Profile, reference and source routes emit safe generic 500 responses."""

    async def fail_service(*_args: object, **_kwargs: object) -> typ.NoReturn:
        await asyncio.sleep(0)
        raise case.exception

    monkeypatch.setattr(case.resource_module, case.service_name, fail_service)
    client = testing.TestClient(
        create_app(ApiDependencies(uow_factory=empty_uow_factory))
    )

    response = client.simulate_get(case.path)

    assert response.status_code == 500, "unmapped domain errors must return HTTP 500"
    assert response.json == {
        "code": "internal_error",
        "message": case.expected_message,
        "details": {},
    }, "routes must expose only the generic internal-error envelope"
    assert _CREDENTIAL not in response.text, "responses must omit source credentials"
    assert len(spy_logger.calls) == 1, "each unmapped route error must log once"
    level, message, exc_info = spy_logger.calls[0]
    assert level == "ERROR", "unmapped route errors must log at ERROR"
    assert _CREDENTIAL not in message, "logs must redact credential-like metadata"
    assert isinstance(exc_info, tuple), "ERROR records must carry exception info"
    assert exc_info[2] is None, "logs must not retain source traceback frames"
