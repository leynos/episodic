"""Verify unmapped profile errors reach the shared handler fallback."""

import asyncio
import typing as typ
import uuid

import falcon
import pytest
from falcon import testing as falcon_testing

from episodic.api.errors import serialize_http_error
from episodic.api.handlers import (
    CreateEntityRequest,
    GetEntityRequest,
    HandlerContext,
    HistoryRequest,
    UpdateEntityRequest,
    handle_create_entity,
    handle_get_entity,
    handle_get_history,
    handle_update_entity,
)
from episodic.api.helpers import build_profile_update_request
from episodic.canonical.pagination import Pagination
from episodic.canonical.profile_templates.types import ProfileTemplateError

if typ.TYPE_CHECKING:
    from tests.fixtures.api_errors import EmptyUnitOfWorkFactory, SpyLogger

_ENTITY_ID = uuid.UUID("00000000-0000-0000-0000-000000000007")


class _UnexpectedProfileTemplateError(ProfileTemplateError):
    """Represent a profile/template error with no dedicated HTTP mapping."""


class _HandlerCase(typ.NamedTuple):
    """Pair a handler path with its source exception for propagation checks."""

    name: str
    source_exception: _UnexpectedProfileTemplateError


class _HasEnvelopeMetadata(typ.Protocol):
    """Describe the error-envelope metadata attached to Falcon errors."""

    envelope_code: str
    envelope_details: dict[str, object]


def _serialize_entity(_entity: object, _revision: int) -> dict[str, object]:
    """Return a stable value if an error handler unexpectedly succeeds."""
    return {}


def _serialize_history_entry(_entry: object) -> dict[str, object]:
    """Return a stable value if a history handler unexpectedly succeeds."""
    return {}


async def _run_handler(
    case: _HandlerCase,
    empty_uow_factory: EmptyUnitOfWorkFactory,
) -> None:
    """Invoke one shared handler with a service that raises ``exc``."""
    exc = case.source_exception

    async def fail_service(
        _uow: object,
        **_kwargs: object,
    ) -> typ.NoReturn:
        """Raise the case-specific error instead of calling a service."""
        await asyncio.sleep(0)
        raise exc

    context = HandlerContext(empty_uow_factory)

    match case.name:
        case "get-entity":
            await handle_get_entity(
                GetEntityRequest(
                    context,
                    str(_ENTITY_ID),
                    "profile_id",
                    fail_service,
                    _serialize_entity,
                )
            )
        case "get-history":
            await handle_get_history(
                HistoryRequest(
                    context,
                    str(_ENTITY_ID),
                    "profile_id",
                    fail_service,
                    _serialize_history_entry,
                    Pagination(limit=1, offset=0),
                )
            )
        case "update-entity":
            await handle_update_entity(
                UpdateEntityRequest(
                    context,
                    str(_ENTITY_ID),
                    "profile_id",
                    {"expected_revision": 1, "title": "Profile", "configuration": {}},
                    ("expected_revision", "title", "configuration"),
                    build_profile_update_request,
                    fail_service,
                    _serialize_entity,
                )
            )
        case "create-entity":
            await handle_create_entity(
                CreateEntityRequest(
                    context,
                    {},
                    (),
                    lambda _payload: {},
                    fail_service,
                    _serialize_entity,
                )
            )
        case _:
            pytest.fail(f"Unexpected handler name: {case.name}")


@pytest.mark.parametrize(
    "handler_name",
    ["get-entity", "get-history", "update-entity", "create-entity"],
)
def test_shared_handlers_defer_unmapped_error_logging_to_serializer(
    handler_name: str,
    spy_logger: SpyLogger,
    empty_uow_factory: EmptyUnitOfWorkFactory,
) -> None:
    """Shared handlers map failures without owning the logging side-effect."""
    source_exception = _UnexpectedProfileTemplateError(
        "Service failure.",
        entity_id=str(_ENTITY_ID),
    )
    with pytest.raises(falcon.HTTPInternalServerError) as raised_error:
        asyncio.run(
            _run_handler(
                _HandlerCase(handler_name, source_exception),
                empty_uow_factory,
            )
        )

    envelope = typ.cast("_HasEnvelopeMetadata", raised_error.value)
    assert envelope.envelope_code == "internal_error", (
        "unmapped profile errors must use the internal-error envelope"
    )
    assert envelope.envelope_details == {}, (
        "unmapped profile errors must not expose exception-derived details"
    )
    assert not spy_logger.calls, "handlers must not emit unmapped-error logs"
    response = falcon.Response()
    serialize_http_error(
        falcon_testing.create_req(),
        response,
        raised_error.value,
        emit_error=spy_logger,
    )
    assert response.media == {
        "code": "internal_error",
        "message": "Unexpected profile/template error.",
        "details": {},
    }, "the serializer must preserve the generic internal-error envelope"
    assert len(spy_logger.calls) == 1, "the HTTP boundary must log exactly once"
    assert spy_logger.calls[0][0] == "ERROR", "unmapped paths must log at ERROR"
