"""Boundary tests for durable orchestration checkpoint payload DTOs."""

import collections.abc as cabc
import dataclasses as dc
import datetime as dt
import enum
import json
import types
import typing as typ

import pytest
from hypothesis import given
from hypothesis import strategies as st

from episodic.llm import LLMProviderOperation, LLMUsage, ProviderCallUsage
from episodic.orchestration._checkpoint_dto import (
    WorkflowCheckpoint,
    WorkflowStepIdentity,
)
from episodic.orchestration._payload_dto import (
    ActionExecutionResult,
    ExecutionPlan,
    PlannedAction,
    PlannerResult,
)

_CHECKPOINT_PAYLOAD_DTOS: tuple[type[object], ...] = (
    ActionExecutionResult,
    ExecutionPlan,
    PlannedAction,
    PlannerResult,
    WorkflowCheckpoint,
    WorkflowStepIdentity,
)
_ALLOWED_LEAF_TYPES: tuple[type[object], ...] = (
    str,
    int,
    float,
    bool,
    dt.datetime,
    LLMUsage,
    ProviderCallUsage,
    LLMProviderOperation,
)
_RUNTIME_VALIDATED_JSON_FIELDS: frozenset[tuple[type[object], str]] = frozenset({
    (WorkflowCheckpoint, "payload"),
})
_NON_PERSISTED_ATTACHMENT_FIELDS: frozenset[tuple[type[object], str]] = frozenset({
    (ActionExecutionResult, "guest_bios_result"),
    (ActionExecutionResult, "show_notes_result"),
})
_JSON_SCALAR_STRATEGY: st.SearchStrategy[object] = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(),
    st.floats(allow_nan=False, allow_infinity=False),
    st.text(),
)
_JSON_VALUE_STRATEGY: st.SearchStrategy[object] = st.recursive(
    _JSON_SCALAR_STRATEGY,
    lambda children: st.one_of(
        st.lists(children, max_size=4),
        st.dictionaries(st.text(), children, max_size=4),
    ),
    max_leaves=12,
)
_UNION_ORIGINS: frozenset[object] = frozenset({typ.Union, types.UnionType})
_SEQUENCE_ORIGINS: frozenset[object] = frozenset({list, cabc.Sequence})
_MAPPING_ORIGINS: frozenset[object] = frozenset({dict, cabc.Mapping})


def test_checkpoint_payload_dtos_use_provider_neutral_field_types() -> None:
    """Checkpoint payload DTO fields stay within provider-neutral types."""
    rejected_fields: list[str] = []
    for dto_type in _CHECKPOINT_PAYLOAD_DTOS:
        type_hints = typ.get_type_hints(dto_type)
        for field in dc.fields(dto_type):
            if (dto_type, field.name) in (
                _RUNTIME_VALIDATED_JSON_FIELDS | _NON_PERSISTED_ATTACHMENT_FIELDS
            ):
                continue
            field_type = type_hints[field.name]
            if not _is_provider_neutral_type(field_type):
                rejected_fields.append(
                    f"{dto_type.__module__}.{dto_type.__qualname__}.{field.name}: "
                    f"{field_type!r}"
                )

    assert not rejected_fields


def test_workflow_checkpoint_rejects_non_json_payload_values() -> None:
    """WorkflowCheckpoint rejects payload values that cannot be serialised."""
    with pytest.raises(
        TypeError,
        match="payload must be JSON-serializable",
    ):
        WorkflowCheckpoint(
            checkpoint_id="checkpoint-1",
            workflow_id="workflow-1",
            workflow_type="generation_orchestration",
            step_name="execute",
            idempotency_key="workflow-1:generation_orchestration:execute:action-1:0",
            payload={"bad": object()},
        )


@given(payload=_JSON_VALUE_STRATEGY)
def test_workflow_checkpoint_payload_round_trips_through_json(payload: object) -> None:
    """Any valid checkpoint payload value survives JSON serialisation unchanged."""
    checkpoint = WorkflowCheckpoint(
        checkpoint_id="checkpoint-1",
        workflow_id="workflow-1",
        workflow_type="generation_orchestration",
        step_name="execute",
        idempotency_key="workflow-1:generation_orchestration:execute:action-1:0",
        payload={"value": payload},
    )

    encoded = json.dumps(checkpoint.payload, sort_keys=True)

    assert json.loads(encoded) == checkpoint.payload


def _is_provider_neutral_type(field_type: object) -> bool:
    """Return whether a DTO field type can cross the checkpoint boundary."""
    if field_type is None or field_type is types.NoneType:
        return True
    if isinstance(field_type, type):
        return _is_provider_neutral_leaf_type(field_type)
    origin = typ.get_origin(field_type)
    arguments = typ.get_args(field_type)
    return _is_provider_neutral_origin(origin, arguments)


def _is_provider_neutral_leaf_type(field_type: type[object]) -> bool:
    """Return whether a concrete type is allowed in checkpoint DTO fields."""
    return (
        field_type in _ALLOWED_LEAF_TYPES
        or issubclass(field_type, enum.Enum)
        or field_type in _CHECKPOINT_PAYLOAD_DTOS
    )


def _is_provider_neutral_origin(
    origin: object,
    arguments: tuple[object, ...],
) -> bool:
    """Return whether a generic annotation origin is checkpoint-neutral."""
    if origin in _UNION_ORIGINS:
        return all(_is_provider_neutral_type(argument) for argument in arguments)
    if origin is typ.Literal:
        return all(_is_provider_neutral_literal(argument) for argument in arguments)
    if origin is tuple:
        return _is_provider_neutral_tuple(arguments)
    if origin in _SEQUENCE_ORIGINS:
        return all(_is_provider_neutral_type(argument) for argument in arguments)
    if origin in _MAPPING_ORIGINS:
        key_type, value_type = arguments
        return key_type is str and _is_provider_neutral_type(value_type)
    return False


def _is_provider_neutral_tuple(arguments: tuple[object, ...]) -> bool:
    """Return whether tuple annotation arguments are checkpoint-neutral."""
    if arguments[-1:] == (Ellipsis,):
        return _is_provider_neutral_type(arguments[0])
    return all(_is_provider_neutral_type(argument) for argument in arguments)


def _is_provider_neutral_literal(value: object) -> bool:
    """Return whether a literal annotation value is provider-neutral."""
    return value is None or isinstance(value, (str, int, float, bool, enum.Enum))
