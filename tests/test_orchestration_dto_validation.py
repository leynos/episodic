"""Tests for DTO validation in GenerationOrchestrationConfig and PlannedAction."""

import typing as typ

import pytest

from episodic.llm import LLMProviderOperation, LLMUsage
from episodic.orchestration import (
    ActionExecutionResult,
    ActionKind,
    ExecutionPlan,
    GenerationOrchestrationConfig,
    GenerationOrchestrationRequest,
    GenerationOrchestrationResult,
    ModelTier,
    PlannedAction,
    StructuredGenerationPlanner,
)
from tests._orchestration_fakes import (
    _config,
    _FakeLLMPort,
)


def _empty_usage() -> LLMUsage:
    """Return deterministic zero-token usage for DTO aggregate tests."""
    return LLMUsage(input_tokens=0, output_tokens=0, total_tokens=0)


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


@pytest.mark.parametrize(
    ("field_name", "expected_message"),
    [
        ("planning_provider_operation", "Unknown planning_provider_operation"),
        ("execution_provider_operation", "Unknown execution_provider_operation"),
    ],
)
def test_config_rejects_unknown_provider_operation(
    field_name: str,
    expected_message: str,
) -> None:
    """Reject any unknown provider operation field for planning/execution."""
    kwargs: dict[str, object] = {
        "planning_model": "gpt-4.1",
        "execution_model": "gpt-4o-mini",
    }
    kwargs[field_name] = "not_a_real_op"
    with pytest.raises(ValueError, match=expected_message):
        GenerationOrchestrationConfig(**typ.cast("typ.Any", kwargs))


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


def test_action_execution_result_normalizes_string_enum_fields() -> None:
    """Action execution results should expose enum instances after construction."""
    result = ActionExecutionResult(
        action_id="action-1",
        action_kind=typ.cast("ActionKind", "generate_show_notes"),
        model_tier=typ.cast("ModelTier", "execution"),
        model="gpt-4o-mini",
        summary="Generated show notes.",
    )

    assert result.action_kind == ActionKind.GENERATE_SHOW_NOTES
    assert result.model_tier == ModelTier.EXECUTION


@pytest.mark.parametrize(
    ("dto_type", "base_kwargs", "field_name", "field_value", "expected_match"),
    [
        (
            PlannedAction,
            {
                "action_id": "action-1",
                "action_kind": ActionKind.GENERATE_SHOW_NOTES,
                "rationale": "Generate notes.",
                "model_tier": ModelTier.EXECUTION,
            },
            "action_kind",
            typ.cast("ActionKind", object()),
            "Unknown action kind",
        ),
        (
            PlannedAction,
            {
                "action_id": "action-1",
                "action_kind": ActionKind.GENERATE_SHOW_NOTES,
                "rationale": "Generate notes.",
                "model_tier": ModelTier.EXECUTION,
            },
            "model_tier",
            typ.cast("ModelTier", object()),
            "Unknown model tier",
        ),
        (
            ActionExecutionResult,
            {
                "action_id": "action-1",
                "action_kind": ActionKind.GENERATE_SHOW_NOTES,
                "model_tier": ModelTier.EXECUTION,
                "model": "gpt-4o-mini",
                "summary": "Generated show notes.",
            },
            "action_kind",
            typ.cast("ActionKind", "unknown_action"),
            "Unknown action kind",
        ),
        (
            ActionExecutionResult,
            {
                "action_id": "action-1",
                "action_kind": ActionKind.GENERATE_SHOW_NOTES,
                "model_tier": ModelTier.EXECUTION,
                "model": "gpt-4o-mini",
                "summary": "Generated show notes.",
            },
            "model_tier",
            typ.cast("ModelTier", "unknown_tier"),
            "Unknown model tier",
        ),
    ],
)
def test_enum_shaped_dtos_reject_unknown_enum_fields(
    dto_type: type[PlannedAction] | type[ActionExecutionResult],
    base_kwargs: dict[str, object],
    field_name: str,
    field_value: ActionKind | ModelTier,
    expected_match: str,
) -> None:
    """Enum-shaped orchestration DTOs should reject invalid enum values."""
    kwargs = dict(base_kwargs)
    kwargs[field_name] = field_value

    with pytest.raises(ValueError, match=expected_match):
        dto_type(**typ.cast("typ.Any", kwargs))


def test_generation_orchestration_result_freezes_action_results() -> None:
    """Generation results should freeze mutable action result iterables."""
    action_result = ActionExecutionResult(
        action_id="action-1",
        action_kind=ActionKind.GENERATE_SHOW_NOTES,
        model_tier=ModelTier.EXECUTION,
        model="gpt-4o-mini",
        summary="Generated show notes.",
    )
    aggregate = GenerationOrchestrationResult(
        plan=ExecutionPlan(
            plan_version="1",
            selected_planning_model="gpt-4.1",
            selected_execution_model="gpt-4o-mini",
            steps=(),
        ),
        action_results=typ.cast("tuple[ActionExecutionResult, ...]", [action_result]),
        planner_usage=_empty_usage(),
        total_usage=_empty_usage(),
    )

    assert aggregate.action_results == (action_result,)
    assert isinstance(aggregate.action_results, tuple), (
        "action_results should be frozen as a tuple"
    )


def test_generation_orchestration_result_rejects_invalid_action_results() -> None:
    """Generation results should reject non-action-result payloads."""
    with pytest.raises(TypeError, match="action_results\\[0\\]"):
        GenerationOrchestrationResult(
            plan=ExecutionPlan(
                plan_version="1",
                selected_planning_model="gpt-4.1",
                selected_execution_model="gpt-4o-mini",
                steps=(),
            ),
            action_results=typ.cast("tuple[ActionExecutionResult, ...]", [object()]),
            planner_usage=_empty_usage(),
            total_usage=_empty_usage(),
        )
