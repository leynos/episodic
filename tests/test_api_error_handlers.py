"""Verify unmapped profile errors reach the shared handler fallback."""

import asyncio
import typing as typ
import uuid

import falcon
import pytest

from episodic.api.handlers import (
    HistoryRequest,
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


def _serialize_entity(_entity: object, _revision: int) -> dict[str, object]:
    """Return a stable value if an error handler unexpectedly succeeds."""
    return {}


def _serialize_history_entry(_entry: object) -> dict[str, object]:
    """Return a stable value if a history handler unexpectedly succeeds."""
    return {}


async def _run_handler(
    handler_name: str,
    exc: ProfileTemplateError,
    empty_uow_factory: EmptyUnitOfWorkFactory,
) -> None:
    """Invoke one shared handler with a service that raises ``exc``."""

    async def fail_service(
        _uow: object,
        **_kwargs: object,
    ) -> tuple[object, int]:
        await asyncio.sleep(0)
        raise exc

    async def fail_history_service(
        _uow: object,
        *,
        parent_id: uuid.UUID,
        page: Pagination,
    ) -> tuple[list[object], int]:
        del parent_id, page
        await asyncio.sleep(0)
        raise exc

    match handler_name:
        case "get-entity":
            await handle_get_entity(
                empty_uow_factory,
                str(_ENTITY_ID),
                "profile_id",
                fail_service,
                _serialize_entity,
            )
        case "get-history":
            await handle_get_history(
                empty_uow_factory,
                HistoryRequest(
                    entity_id=str(_ENTITY_ID),
                    id_field_name="profile_id",
                    service_fn=fail_history_service,
                    serializer_fn=_serialize_history_entry,
                    page=Pagination(limit=1, offset=0),
                ),
            )
        case "update-entity":
            await handle_update_entity(
                empty_uow_factory,
                str(_ENTITY_ID),
                "profile_id",
                {"expected_revision": 1, "title": "Profile", "configuration": {}},
                ("expected_revision", "title", "configuration"),
                build_profile_update_request,
                fail_service,
                _serialize_entity,
            )
        case "create-entity":
            await handle_create_entity(
                empty_uow_factory,
                {},
                required_fields=(),
                kwargs_builder=lambda _payload: {},
                service_fn=fail_service,
                serializer_fn=_serialize_entity,
            )
        case _:
            pytest.fail(f"Unexpected handler name: {handler_name}")


@pytest.mark.parametrize(
    "handler_name",
    ["get-entity", "get-history", "update-entity", "create-entity"],
)
def test_shared_handlers_log_unmapped_profile_errors(
    handler_name: str,
    spy_logger: SpyLogger,
    empty_uow_factory: EmptyUnitOfWorkFactory,
) -> None:
    """Every shared profile handler routes its unmapped errors to the mapper."""
    exc = _UnexpectedProfileTemplateError("Service failure.", entity_id=str(_ENTITY_ID))

    with pytest.raises(falcon.HTTPInternalServerError) as raised_error:
        asyncio.run(_run_handler(handler_name, exc, empty_uow_factory))

    assert typ.cast("typ.Any", raised_error.value).envelope_code == "internal_error", (
        "unmapped profile errors must use the internal-error envelope"
    )
    assert len(spy_logger.calls) == 1, "each handler error must be logged once"
    level, message, exc_info = spy_logger.calls[0]
    assert level == "ERROR", "unmapped profile errors must log at ERROR"
    assert type(exc).__name__ in message, "logs must identify the exception type"
    assert isinstance(exc_info, tuple), "logs must carry detached exception info"
