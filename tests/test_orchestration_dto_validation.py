"""Tests for DTO validation in GenerationOrchestrationConfig and PlannedAction."""

import typing as typ

import pytest

from episodic.llm import LLMProviderOperation
from episodic.orchestration import (
    ActionKind,
    GenerationOrchestrationConfig,
    GenerationOrchestrationRequest,
    ModelTier,
    PlannedAction,
    StructuredGenerationPlanner,
)
from tests._orchestration_fakes import (
    _config,
    _FakeLLMPort,
)


def test_config_rejects_empty_enabled_action_kinds() -> None:
    """Configuration should reject an empty action vocabulary."""
    with pytest.raises(ValueError, match="enabled_action_kinds must not be empty"):
        GenerationOrchestrationConfig(
            planning_model="gpt-4.1",
            execution_model="gpt-4o-mini",
            enabled_action_kinds=(),
        )


def test_config_normalises_string_action_kinds() -> None:
    """Configuration should accept string-like ActionKind values."""
    config = GenerationOrchestrationConfig(
        planning_model="gpt-4.1",
        execution_model="gpt-4o-mini",
        enabled_action_kinds=("generate_show_notes",),
    )

    assert config.enabled_action_kinds == (ActionKind.GENERATE_SHOW_NOTES,)


def test_planner_rejects_non_json_serializable_template_structure() -> None:
    """Prompt construction should reject non-JSON template structures clearly."""
    planner = StructuredGenerationPlanner(
        llm=_FakeLLMPort([]),
        config=_config(),
    )
    request = GenerationOrchestrationRequest(
        correlation_id="corr-123",
        script_tei_xml="<TEI />",
        template_structure={"bad": object()},
    )

    with pytest.raises(
        ValueError, match="template_structure must be JSON-serializable"
    ):
        planner.build_prompt(request)


def test_config_rejects_unknown_action_kind() -> None:
    """Configuration should fail before unsupported action kinds flow onward."""
    with pytest.raises(
        ValueError,
        match="Unknown action kind: 'unknown_action'",
    ):
        GenerationOrchestrationConfig(
            planning_model="gpt-4.1",
            execution_model="gpt-4o-mini",
            enabled_action_kinds=("unknown_action",),
        )


def test_config_rejects_non_string_text_fields() -> None:
    """Configuration should reject non-string text fields deterministically."""
    with pytest.raises(ValueError, match="planning_model must be a non-empty string"):
        GenerationOrchestrationConfig(
            planning_model=typ.cast("str", object()),
            execution_model="gpt-4o-mini",
        )


def test_config_normalises_string_provider_operations() -> None:
    """Configuration should accept string-like provider-operation values."""
    config = GenerationOrchestrationConfig(
        planning_model="gpt-4.1",
        execution_model="gpt-4o-mini",
        planning_provider_operation="chat_completions",
        execution_provider_operation="chat_completions",
    )

    assert config.planning_provider_operation == LLMProviderOperation.CHAT_COMPLETIONS
    assert config.execution_provider_operation == LLMProviderOperation.CHAT_COMPLETIONS


@pytest.mark.parametrize("unknown_operation", ["not_a_real_op"])
def test_config_rejects_unknown_planning_provider_operation(
    unknown_operation: str,
) -> None:
    """Configuration should reject unknown planning provider operations."""
    with pytest.raises(
        ValueError,
        match="Unknown planning_provider_operation",
    ):
        GenerationOrchestrationConfig(
            planning_model="gpt-4.1",
            execution_model="gpt-4o-mini",
            planning_provider_operation=unknown_operation,
        )


@pytest.mark.parametrize("unknown_operation", ["not_a_real_op"])
def test_config_rejects_unknown_execution_provider_operation(
    unknown_operation: str,
) -> None:
    """Configuration should reject unknown execution provider operations."""
    with pytest.raises(
        ValueError,
        match="Unknown execution_provider_operation",
    ):
        GenerationOrchestrationConfig(
            planning_model="gpt-4.1",
            execution_model="gpt-4o-mini",
            execution_provider_operation=unknown_operation,
        )


def test_planned_action_normalizes_string_enum_fields() -> None:
    """Planned actions should normalize string enum fields at construction."""
    action = PlannedAction(
        action_id="action-1",
        action_kind="generate_show_notes",
        rationale="Generate notes.",
        model_tier="execution",
    )

    assert action.action_kind == ActionKind.GENERATE_SHOW_NOTES
    assert action.model_tier == ModelTier.EXECUTION


@pytest.mark.parametrize(
    ("required_inputs", "expected_match"),
    [
        (["  "], "required_inputs must be a non-empty string"),
        ("oops", "required_inputs must be an iterable of non-empty strings"),
        (None, "required_inputs must be an iterable of non-empty strings"),
    ],
)
def test_planned_action_rejects_invalid_required_inputs(
    required_inputs: object,
    expected_match: str,
) -> None:
    """Planned actions should reject malformed required input declarations."""
    with pytest.raises(ValueError, match=expected_match):
        PlannedAction(
            action_id="action-1",
            action_kind=ActionKind.GENERATE_SHOW_NOTES,
            rationale="Generate notes.",
            model_tier=ModelTier.EXECUTION,
            required_inputs=typ.cast("tuple[str, ...]", required_inputs),
        )


def test_planned_action_normalizes_required_input_iterables() -> None:
    """Planned actions should freeze valid required input iterables as tuples."""
    action = PlannedAction(
        action_id="action-1",
        action_kind=ActionKind.GENERATE_SHOW_NOTES,
        rationale="Generate notes.",
        model_tier=ModelTier.EXECUTION,
        required_inputs=typ.cast("tuple[str, ...]", ["valid", "inputs"]),
    )

    assert action.required_inputs == (
        "valid",
        "inputs",
    ), "required_inputs should be normalised into a tuple"


@pytest.mark.parametrize(
    ("field_name", "field_value", "expected_match"),
    [
        ("action_kind", typ.cast("ActionKind", object()), "Unknown action kind"),
        ("model_tier", typ.cast("ModelTier", object()), "Unknown model tier"),
    ],
)
def test_planned_action_rejects_unknown_enum_fields(
    field_name: str,
    field_value: ActionKind | ModelTier,
    expected_match: str,
) -> None:
    """Planned actions should reject invalid enum-like field values."""
    kwargs: dict[str, object] = {
        "action_id": "action-1",
        "action_kind": ActionKind.GENERATE_SHOW_NOTES,
        "rationale": "Generate notes.",
        "model_tier": ModelTier.EXECUTION,
    }
    kwargs[field_name] = field_value

    with pytest.raises(ValueError, match=expected_match):
        PlannedAction(**typ.cast("typ.Any", kwargs))
