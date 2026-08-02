"""Unit tests for private API helper behaviour in ``episodic.api.helpers``.

These tests focus on update-request assembly and payload validation used by
Falcon resource adapters.

Run these tests directly with:

```bash
python -m pytest -v tests/test_api_helpers.py
```

Expected behaviour: all tests pass when update wiring and payload validation
are correct.
"""

import typing as typ
import uuid

import falcon
import pytest

from episodic.api import helpers
from episodic.canonical.profile_templates import AuditMetadata

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from episodic.api.types import JsonPayload


def _call_builder_with_payload(
    builder: cabc.Callable[..., object],
    payload: JsonPayload,
) -> object:
    """Invoke a helper builder with the right argument shape for the test."""
    if builder in {
        helpers.build_profile_update_request,
        helpers.build_template_update_request,
    }:
        return builder(uuid.uuid4(), payload)
    return builder(payload)


class TestTypedUpdateRequest:
    """Tests for typed update-request composition helper behavior."""

    @staticmethod
    def test_build_typed_update_request_passes_payload_and_uses_data_builder(
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Pass payload through and use parsed components from data_builder."""
        captured: dict[str, object] = {}
        entity_id = uuid.uuid4()

        def sentinel_data_builder(payload: dict[str, object]) -> str:
            return typ.cast("str", payload["title"])

        def fake_build_update_kwargs(
            payload: dict[str, object],
            *,
            data_builder: cabc.Callable[[dict[str, object]], str],
        ) -> helpers._ParsedUpdatePayload[str]:
            captured["payload"] = payload
            captured["data_builder"] = data_builder
            return helpers._ParsedUpdatePayload(
                expected_revision=3,
                data="payload-fields",
                audit=AuditMetadata(actor="editor@example.com", note="update"),
            )

        monkeypatch.setattr(
            helpers,
            "_build_update_kwargs",
            fake_build_update_kwargs,
        )

        request = helpers._build_typed_update_request(
            entity_id,
            {"title": "updated"},
            data_builder=sentinel_data_builder,
            request_builder=lambda eid, rev, fields, audit: {
                "entity_id": eid,
                "expected_revision": rev,
                "fields": fields,
                "audit": audit,
            },
        )

        assert captured["payload"] == {"title": "updated"}, (
            "Expected helper to pass payload through to _build_update_kwargs."
        )
        assert captured["data_builder"] is sentinel_data_builder, (
            "Expected _build_typed_update_request to forward the same "
            "data_builder callable to _build_update_kwargs."
        )
        assert request == {
            "entity_id": entity_id,
            "expected_revision": 3,
            "fields": "payload-fields",
            "audit": AuditMetadata(actor="editor@example.com", note="update"),
        }, "Expected request builder output to use parsed update components."


class TestGuardrailValidation:
    """Tests for guardrail object validation in API helper builders."""

    @staticmethod
    @pytest.mark.parametrize(
        ("builder", "payload"),
        [
            pytest.param(
                helpers.build_profile_create_kwargs,
                {
                    "slug": "profile",
                    "title": "Profile",
                    "configuration": {"tone": "neutral"},
                    "guardrails": None,
                },
                id="profile-create-null",
            ),
            pytest.param(
                helpers.build_profile_update_request,
                {
                    "expected_revision": 1,
                    "title": "Profile",
                    "configuration": {"tone": "neutral"},
                    "guardrails": [],
                },
                id="profile-update-list",
            ),
            pytest.param(
                helpers.build_template_create_kwargs,
                {
                    "series_profile_id": str(uuid.uuid4()),
                    "slug": "template",
                    "title": "Template",
                    "structure": {"segments": ["intro"]},
                    "guardrails": "invalid",
                },
                id="template-create-string",
            ),
            pytest.param(
                helpers.build_template_update_request,
                {
                    "expected_revision": 1,
                    "title": "Template",
                    "structure": {"segments": ["intro"]},
                    "guardrails": None,
                },
                id="template-update-null",
            ),
        ],
    )
    def test_builders_reject_non_object_guardrails(
        builder: cabc.Callable[..., object],
        payload: JsonPayload,
    ) -> None:
        """Reject null and other non-object guardrail payloads."""
        with pytest.raises(falcon.HTTPBadRequest, match=r"400 Bad Request") as exc_info:
            _ = _call_builder_with_payload(builder, payload)

        assert exc_info.value.description == "guardrails must be a JSON object.", (
            "Expected helper builders to reject non-object guardrails consistently."
        )
