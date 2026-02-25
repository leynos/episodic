"""Unit tests for private API helper behavior in ``episodic.api.helpers``.

These tests focus on payload-to-dataclass mapping and update-request assembly
used by Falcon resource adapters. They validate required/optional payload
handling, key remapping behavior, and generic update-request wiring.

Run these tests directly with:

```bash
python -m pytest -v tests/test_api_helpers.py
```

Expected behavior:
- All tests pass when helper payload mapping and update wiring are correct.
- Missing required mapped fields raise ``falcon.HTTPBadRequest`` and preserve
  the expected description text.
"""

from __future__ import annotations

import dataclasses as dc
import typing as typ
import uuid

import falcon
import pytest

from episodic.api import helpers
from episodic.canonical.profile_templates import AuditMetadata

if typ.TYPE_CHECKING:
    import collections.abc as cabc


@dc.dataclass(frozen=True, slots=True)
class _ExampleFields:
    """Example dataclass used to test generic payload mapping."""

    title: str
    description: str | None
    configuration: dict[str, object]


@dc.dataclass(frozen=True, slots=True)
class _MappedFields:
    """Example dataclass with fields mapped from differently named keys."""

    title: str
    description: str | None
    structure: dict[str, object]


class TestPayloadDataclass:
    """Tests for generic payload-to-dataclass mapping helper behavior."""

    @staticmethod
    def test_build_payload_dataclass_maps_required_and_optional_fields() -> None:
        """Build dataclass values from required and optional payload fields."""
        payload = {
            "title": "Show title",
            "configuration": {"tone": "precise"},
        }

        parsed = helpers._build_payload_dataclass(
            payload,
            dc_type=_ExampleFields,
            field_map={
                "title": ("title", False),
                "description": ("description", True),
                "configuration": ("configuration", False),
            },
        )

        assert parsed == _ExampleFields(
            title="Show title",
            description=None,
            configuration={"tone": "precise"},
        ), "Expected payload values to map to _ExampleFields."

    @staticmethod
    def test_build_payload_dataclass_supports_key_remapping() -> None:
        """Map payload keys with different names to dataclass fields."""
        payload = {
            "profile_title": "Remapped title",
            "profile_description": "Remapped description",
            "template_structure": {"segments": ["intro", "outro"]},
        }

        parsed = helpers._build_payload_dataclass(
            payload,
            dc_type=_MappedFields,
            field_map={
                "title": ("profile_title", False),
                "description": ("profile_description", True),
                "structure": ("template_structure", False),
            },
        )

        assert parsed == _MappedFields(
            title="Remapped title",
            description="Remapped description",
            structure={"segments": ["intro", "outro"]},
        ), "Expected remapped payload keys to populate _MappedFields."

    @staticmethod
    def test_build_payload_dataclass_raises_when_required_field_is_missing() -> None:
        """Raise HTTP 400 when a required field is absent from the payload."""
        payload = {
            "configuration": {"tone": "precise"},
        }

        with pytest.raises(
            falcon.HTTPBadRequest,
            match=r"400 Bad Request",
        ) as exc_info:
            helpers._build_payload_dataclass(
                payload,
                dc_type=_ExampleFields,
                field_map={
                    "title": ("title", False),
                    "description": ("description", True),
                    "configuration": ("configuration", False),
                },
            )
        assert exc_info.value.description == "Missing required field: title", (
            "Expected missing required fields to preserve the HTTP 400 description."
        )


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
