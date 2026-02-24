"""Unit tests for API payload helper functions."""

from __future__ import annotations

import dataclasses as dc
import typing as typ
import uuid

import pytest

from episodic.api import helpers
from episodic.canonical.profile_templates import AuditMetadata


@dc.dataclass(frozen=True, slots=True)
class _ExampleFields:
    """Example dataclass used to test generic payload mapping."""

    title: str
    description: str | None
    configuration: dict[str, object]


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
    )


def test_build_payload_dataclass_raises_when_required_field_is_missing() -> None:
    """Raise KeyError when a required field is absent from the payload."""
    payload = {
        "configuration": {"tone": "precise"},
    }

    with pytest.raises(KeyError):
        helpers._build_payload_dataclass(
            payload,
            dc_type=_ExampleFields,
            field_map={
                "title": ("title", False),
                "description": ("description", True),
                "configuration": ("configuration", False),
            },
        )


def test_build_typed_update_request_uses_selected_data_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pass dynamic data key values through to request builder."""
    captured: dict[str, object] = {}
    entity_id = uuid.uuid4()

    def fake_build_update_kwargs(
        payload: dict[str, object],
        *,
        data_key: str,
        data_builder: typ.Callable[[dict[str, object]], str],
    ) -> dict[str, object]:
        captured["payload"] = payload
        captured["data_key"] = data_key
        captured["data_builder"] = data_builder
        return {
            "expected_revision": 3,
            data_key: "payload-fields",
            "audit": AuditMetadata(actor="editor@example.com", note="update"),
        }

    monkeypatch.setattr(helpers, "_build_update_kwargs", fake_build_update_kwargs)

    request = helpers._build_typed_update_request(
        entity_id,
        {"title": "updated"},
        data_key="fields",
        data_builder=lambda payload: typ.cast("str", payload["title"]),
        request_builder=lambda eid, rev, fields, audit: {
            "entity_id": eid,
            "expected_revision": rev,
            "fields": fields,
            "audit": audit,
        },
    )

    assert captured["payload"] == {"title": "updated"}
    assert captured["data_key"] == "fields"
    assert request == {
        "entity_id": entity_id,
        "expected_revision": 3,
        "fields": "payload-fields",
        "audit": AuditMetadata(actor="editor@example.com", note="update"),
    }
