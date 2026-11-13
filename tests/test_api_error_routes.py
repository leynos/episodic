"""Verify unmapped errors cross the Falcon API boundary safely."""

import asyncio
import dataclasses as dc
import typing as typ
from unittest import mock

import pytest
from falcon import testing

import episodic.api.app as api_app
import episodic.api.errors as api_errors
from episodic.api import ApiDependencies, create_app
from episodic.api.authorization import PermitAll, StaticBearerTokenAuthorization
from episodic.api.resources import reference_documents, series_profiles, source_intake
from episodic.api.source_intake_support import ParsedUpload
from episodic.canonical.profile_templates.types import ProfileTemplateError
from episodic.canonical.reference_documents.types import ReferenceDocumentError
from episodic.canonical.source_intake_errors import SourceIntakeError

if typ.TYPE_CHECKING:
    import collections.abc as cabc
    import types

    from tests.fixtures.api_errors import EmptyUnitOfWorkFactory, SpyLogger

_ENTITY_ID = "00000000-0000-0000-0000-000000000007"
_CREDENTIAL = "route-test-secret-marker"
_AUTHORIZATION = {"Authorization": "Bearer route-test-token"}


@dc.dataclass(frozen=True, slots=True)
class _RouteCase:
    """Describe one API route that maps an unmapped domain error."""

    resource_module: types.ModuleType
    service_name: str
    exception: Exception
    path: str
    expected_message: str
    method: str = "GET"
    payload: dict[str, object] | None = None
    authenticated: bool = False
    has_object_store: bool = False
    is_idempotent: bool = False


def _failing_service(
    exception: Exception,
) -> cabc.Callable[..., cabc.Awaitable[typ.NoReturn]]:
    """Build an async service replacement that raises one domain error."""

    async def fail_service(*_args: object, **_kwargs: object) -> typ.NoReturn:
        """Raise the selected error from a resource service boundary."""
        await asyncio.sleep(0)
        raise exception

    return fail_service


async def _bypass_idempotency(
    _uow_factory: object,
    *,
    context: object,
    work: cabc.Callable[[], cabc.Awaitable[object]],
) -> object:
    """Run route work directly for error-boundary tests."""
    del context
    return await work()


async def _parsed_upload_form(
    *_args: object,
    **_kwargs: object,
) -> ParsedUpload:
    """Return valid upload metadata so the service boundary is reached."""
    await asyncio.sleep(0)
    return ParsedUpload(
        payload=b"content",
        payload_sha256="sha256:unused-test-hash",
        content_type="text/plain",
        declared_size=7,
        declared_sha256=None,
        metadata={},
    )


def _patch_source_intake_route(
    case: _RouteCase,
    default_logger: mock.Mock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Replace the route's service and unrelated I/O boundaries for one test."""
    monkeypatch.setattr(
        case.resource_module,
        case.service_name,
        _failing_service(case.exception),
    )
    monkeypatch.setattr(api_app, "log_error", default_logger)
    monkeypatch.setattr(api_errors, "log_error", default_logger)
    if case.is_idempotent:
        monkeypatch.setattr(source_intake, "run_idempotent", _bypass_idempotency)
    if case.method == "POST" and case.path == "/v1/uploads":
        monkeypatch.setattr(source_intake, "parse_upload_form", _parsed_upload_form)


def _source_intake_dependencies(
    case: _RouteCase,
    empty_uow_factory: EmptyUnitOfWorkFactory,
    spy_logger: SpyLogger,
) -> ApiDependencies:
    """Build app dependencies with the test logger and required route ports."""
    authorization = (
        StaticBearerTokenAuthorization(
            token=_AUTHORIZATION["Authorization"].removeprefix("Bearer "),
            principal_id="route-test-principal",
        )
        if case.authenticated
        else PermitAll()
    )
    return ApiDependencies(
        uow_factory=empty_uow_factory,
        authorization=authorization,
        object_store=mock.Mock() if case.has_object_store else None,
        unmapped_error_emitter=spy_logger,
    )


def _source_intake_headers(case: _RouteCase) -> dict[str, str]:
    """Build the authenticated and idempotency headers required by a case."""
    headers = dict(_AUTHORIZATION) if case.authenticated else {}
    if case.is_idempotent:
        headers["Idempotency-Key"] = "route-error-key"
    return headers


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
        """Raise the route case's error from its registered service."""
        await asyncio.sleep(0)
        raise case.exception

    monkeypatch.setattr(case.resource_module, case.service_name, fail_service)
    client = testing.TestClient(
        create_app(
            ApiDependencies(
                uow_factory=empty_uow_factory,
                unmapped_error_emitter=spy_logger,
            )
        )
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
    logged_exception = exc_info[1]
    assert logged_exception is not case.exception, (
        "the boundary must log detached exception information"
    )
    assert logged_exception.__cause__ is None, "logs must omit chained causes"
    assert logged_exception.__context__ is None, "logs must omit exception context"
    assert _CREDENTIAL not in str(logged_exception), (
        "detached exception information must not expose source credentials"
    )


def test_create_app_binds_default_unmapped_error_emitter(
    empty_uow_factory: EmptyUnitOfWorkFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The default app boundary logs safe unmapped errors once."""
    exception = ProfileTemplateError(
        "Profile failure: " + _CREDENTIAL,
        code=_CREDENTIAL,
        entity_id=_CREDENTIAL,
    )

    async def fail_service(*_args: object, **_kwargs: object) -> typ.NoReturn:
        """Raise the test error from the replaced profile service."""
        await asyncio.sleep(0)
        raise exception

    emit_error = mock.Mock()
    monkeypatch.setattr(api_app, "log_error", emit_error)
    monkeypatch.setattr(series_profiles, "get_entity_with_revision", fail_service)
    client = testing.TestClient(
        create_app(ApiDependencies(uow_factory=empty_uow_factory))
    )
    response = client.simulate_get(f"/v1/series-profiles/{_ENTITY_ID}")

    assert response.status_code == 500, "unmapped errors must remain HTTP 500"
    assert _CREDENTIAL not in response.text, "client responses must redact credentials"
    assert emit_error.call_count == 1, "the default boundary must emit one ERROR record"
    logger, template, *args = emit_error.call_args.args
    assert logger is api_app.logger, "the default boundary must use the app logger"
    message = typ.cast("str", template) % tuple(args)
    assert _CREDENTIAL not in message, "default logs must redact metadata"
    exc_info = emit_error.call_args.kwargs["exc_info"]
    assert isinstance(exc_info, tuple), "default logs must carry detached exc_info"
    assert exc_info[2] is None, "default logs must omit source traceback frames"
    logged_exception = typ.cast("BaseException", exc_info[1])
    assert logged_exception is not exception, "default logs must detach exceptions"
    assert logged_exception.__cause__ is None, "default logs must omit causes"
    assert logged_exception.__context__ is None, "default logs must omit context"
    assert _CREDENTIAL not in str(logged_exception), (
        "default logs must omit credential-like exception text"
    )


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(
            _RouteCase(
                source_intake,
                "register_upload",
                SourceIntakeError("Upload failure: " + _CREDENTIAL),
                "/v1/uploads",
                "Unexpected source-intake error.",
                method="POST",
                authenticated=True,
                has_object_store=True,
                is_idempotent=True,
            ),
            id="uploads-resource",
        ),
        pytest.param(
            _RouteCase(
                source_intake,
                "create_ingestion_job",
                SourceIntakeError("Ingestion-job failure: " + _CREDENTIAL),
                "/v1/ingestion-jobs",
                "Unexpected source-intake error.",
                method="POST",
                payload={"series_profile_id": _ENTITY_ID},
                authenticated=True,
                is_idempotent=True,
            ),
            id="ingestion-jobs-resource",
        ),
        pytest.param(
            _RouteCase(
                source_intake,
                "get_upload",
                SourceIntakeError("Upload lookup failure: " + _CREDENTIAL),
                f"/v1/uploads/{_ENTITY_ID}",
                "Unexpected source-intake error.",
                authenticated=True,
            ),
            id="upload-resource",
        ),
        pytest.param(
            _RouteCase(
                source_intake,
                "get_ingestion_job_status",
                SourceIntakeError("Ingestion-job lookup failure: " + _CREDENTIAL),
                f"/v1/ingestion-jobs/{_ENTITY_ID}",
                "Unexpected source-intake error.",
                authenticated=True,
            ),
            id="ingestion-job-resource",
        ),
        pytest.param(
            _RouteCase(
                source_intake,
                "get_ingestion_job_status",
                SourceIntakeError("Ingestion-job sources failure: " + _CREDENTIAL),
                f"/v1/ingestion-jobs/{_ENTITY_ID}/sources",
                "Unexpected source-intake error.",
                authenticated=True,
            ),
            id="ingestion-job-sources-resource",
        ),
        pytest.param(
            _RouteCase(
                source_intake,
                "get_ingestion_job_status",
                SourceIntakeError(
                    "Ingestion-job source attach failure: " + _CREDENTIAL
                ),
                f"/v1/ingestion-jobs/{_ENTITY_ID}/sources",
                "Unexpected source-intake error.",
                method="POST",
                payload={
                    "type": "source_uri",
                    "source_uri": "https://example.test/source.txt",
                    "source_type": "research_note",
                    "weight": 1.0,
                    "metadata": {},
                },
                authenticated=True,
                is_idempotent=True,
            ),
            id="ingestion-job-sources-create-resource",
        ),
    ],
)
def test_source_intake_routes_use_the_configured_error_emitter(
    case: _RouteCase,
    spy_logger: SpyLogger,
    empty_uow_factory: EmptyUnitOfWorkFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each source-intake resource reaches the app's configured error port."""
    default_logger = mock.Mock()
    _patch_source_intake_route(case, default_logger, monkeypatch)
    client = testing.TestClient(
        create_app(_source_intake_dependencies(case, empty_uow_factory, spy_logger))
    )
    request_headers = _source_intake_headers(case)
    if case.method == "POST":
        response = client.simulate_post(
            case.path,
            headers=request_headers,
            json=case.payload,
        )
    else:
        response = client.simulate_get(case.path, headers=request_headers)

    assert response.status_code == 500, "unmapped resource errors must return HTTP 500"
    assert response.json == {
        "code": "internal_error",
        "message": case.expected_message,
        "details": {},
    }, "source-intake routes must expose the generic internal-error envelope"
    assert len(spy_logger.calls) == 1, "the configured emitter must receive one record"
    assert default_logger.call_count == 0, (
        "resource diagnostics must use the injected emitter"
    )
