"""Ensure reference read resources defer logging to Falcon serialization."""

import asyncio
import dataclasses as dc
import typing as typ
from unittest import mock

import falcon
import pytest
from falcon import testing

import episodic.api.errors as api_errors
from episodic.api.resources import reference_bindings, reference_documents
from episodic.api.resources.reference_bindings import (
    ReferenceBindingResource,
    ReferenceBindingsResource,
)
from episodic.api.resources.reference_documents import (
    ReferenceDocumentResource,
    ReferenceDocumentsResource,
)
from episodic.canonical.reference_documents import ReferenceDocumentError

if typ.TYPE_CHECKING:
    import types

    from tests.fixtures.api_errors import EmptyUnitOfWorkFactory

_PROFILE_ID = "00000000-0000-0000-0000-000000000007"
_DOCUMENT_ID = "00000000-0000-0000-0000-000000000008"
_BINDING_ID = "00000000-0000-0000-0000-000000000009"
_TARGET_ID = "00000000-0000-0000-0000-000000000010"


class _UnexpectedReferenceDocumentError(ReferenceDocumentError):
    """Represent an unmapped failure raised by a reference read service."""


class _HasErrorEnvelope(typ.Protocol):
    """Describe the stable envelope metadata attached to a Falcon error."""

    envelope_code: str
    envelope_details: dict[str, object]


@dc.dataclass(frozen=True, slots=True)
class _ReferenceReadCase:
    """Describe one reference-resource GET method and its service seam."""

    resource_type: type[typ.Any]
    resource_module: types.ModuleType
    service_name: str
    path: str
    path_parameters: dict[str, str]
    expected_description: str
    query_string: str = ""


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(
            _ReferenceReadCase(
                ReferenceDocumentsResource,
                reference_documents,
                "list_reference_documents_paged",
                f"/v1/series-profiles/{_PROFILE_ID}/reference-documents",
                {"profile_id": _PROFILE_ID},
                "Unexpected reference-document error.",
            ),
            id="reference-document-list",
        ),
        pytest.param(
            _ReferenceReadCase(
                ReferenceDocumentResource,
                reference_documents,
                "get_reference_document",
                (
                    f"/v1/series-profiles/{_PROFILE_ID}/reference-documents/"
                    f"{_DOCUMENT_ID}"
                ),
                {"profile_id": _PROFILE_ID, "document_id": _DOCUMENT_ID},
                "Unexpected reference-document error.",
            ),
            id="reference-document-fetch",
        ),
        pytest.param(
            _ReferenceReadCase(
                ReferenceBindingsResource,
                reference_bindings,
                "list_reference_bindings_paged",
                "/v1/reference-bindings",
                {},
                "Unexpected reference-binding error.",
                f"target_kind=series_profile&target_id={_TARGET_ID}",
            ),
            id="reference-binding-list",
        ),
        pytest.param(
            _ReferenceReadCase(
                ReferenceBindingResource,
                reference_bindings,
                "get_reference_binding",
                f"/v1/reference-bindings/{_BINDING_ID}",
                {"binding_id": _BINDING_ID},
                "Unexpected reference-binding error.",
            ),
            id="reference-binding-fetch",
        ),
    ],
)
@pytest.mark.asyncio
async def test_reference_get_resources_do_not_log_before_serialization(
    case: _ReferenceReadCase,
    empty_uow_factory: EmptyUnitOfWorkFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Direct GET handling maps errors without invoking the module logger."""

    async def fail_service(*_args: object, **_kwargs: object) -> typ.NoReturn:
        """Raise an unmapped reference error from the selected service."""
        await asyncio.sleep(0)
        raise _UnexpectedReferenceDocumentError

    module_logger = mock.Mock()
    monkeypatch.setattr(case.resource_module, case.service_name, fail_service)
    monkeypatch.setattr(api_errors, "log_error", module_logger)
    resource = case.resource_type(empty_uow_factory)
    request = testing.create_req(path=case.path, query_string=case.query_string)

    with pytest.raises(falcon.HTTPInternalServerError) as raised:
        await resource.on_get(
            request,
            falcon.Response(),
            **case.path_parameters,
        )

    mapped = typ.cast("_HasErrorEnvelope", raised.value)
    assert raised.value.description == case.expected_description, (
        "read resources must retain the generic internal-error description"
    )
    assert mapped.envelope_code == "internal_error", (
        "read resources must retain the generic envelope code"
    )
    assert mapped.envelope_details == {}, (
        "read resources must not expose exception-derived details"
    )
    module_logger.assert_not_called()
