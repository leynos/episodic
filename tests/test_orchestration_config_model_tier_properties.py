"""Property and boundary tests for orchestration config and model tiers."""

import hypothesis.strategies as st
import pytest
from hypothesis import given, settings

from episodic.llm import LLMProviderOperation
from episodic.orchestration import (
    ActionKind,
    GenerationOrchestrationConfig,
    ModelTier,
    PlannedAction,
    ShowNotesToolExecutor,
    UnsupportedActionError,
)
from tests._orchestration_fakes import (
    _config,
    _FakeLLMPort,
    _request,
)
from tests._orchestration_property_support import (
    KNOWN_ACTION_KIND_STRINGS,
    PropShowNotesGenerator,
)

_ACTION_KIND_SAMPLES: tuple[ActionKind | str, ...] = tuple(ActionKind) + tuple(
    m.value for m in ActionKind
)


@given(st.lists(st.sampled_from(_ACTION_KIND_SAMPLES), min_size=1, max_size=48))
@settings(max_examples=50)
def test_config_normalises_arbitrary_string_and_enum_mixes(
    kinds: list[ActionKind | str],
) -> None:
    """Property test: heterogeneous action vocabularies become ``ActionKind``."""
    cfg = GenerationOrchestrationConfig(
        planning_model="hyp-plan-model",
        execution_model="hyp-exec-model",
        planning_provider_operation=LLMProviderOperation.CHAT_COMPLETIONS,
        execution_provider_operation=LLMProviderOperation.CHAT_COMPLETIONS,
        enabled_action_kinds=tuple(kinds),
    )
    assert all(isinstance(kind, ActionKind) for kind in cfg.enabled_action_kinds)
    assert cfg.enabled_action_kinds == tuple(ActionKind(str(kind)) for kind in kinds)


@given(
    unknown=st.text(min_size=1, max_size=512).filter(
        lambda s: bool(s.strip()) and s.strip() not in KNOWN_ACTION_KIND_STRINGS
    )
)
@settings(max_examples=50)
def test_config_rejects_arbitrary_unknown_action_kind_strings(unknown: str) -> None:
    """Property test: unknown action strings invalidate configuration."""
    with pytest.raises(ValueError, match="Unknown action kind"):
        GenerationOrchestrationConfig(
            planning_model="hyp-plan-model",
            execution_model="hyp-exec-model",
            planning_provider_operation=LLMProviderOperation.CHAT_COMPLETIONS,
            execution_provider_operation=LLMProviderOperation.CHAT_COMPLETIONS,
            enabled_action_kinds=(unknown,),
        )


@pytest.mark.parametrize(
    ("model_tier",),  # noqa: PT006 - requested tuple-shaped parameter list.
    [(tier,) for tier in ModelTier if tier is not ModelTier.EXECUTION],
)
@pytest.mark.asyncio
async def test_planned_action_model_tier_rejection_for_all_non_execution_tiers(
    model_tier: ModelTier,
) -> None:
    """Every planner tier besides execution must be rejected by show-notes."""
    fake_llm = _FakeLLMPort([])
    tool_executor = ShowNotesToolExecutor(llm=fake_llm, config=_config())
    planning_tier_action = PlannedAction(
        action_id="action-1",
        action_kind=ActionKind.GENERATE_SHOW_NOTES,
        rationale="Hypothesis rejects non-execution tiers.",
        model_tier=model_tier,
        required_inputs=("script_tei_xml",),
    )
    with pytest.raises(UnsupportedActionError, match=r"requires ModelTier\.EXECUTION"):
        await tool_executor.execute(planning_tier_action, _request())


@pytest.mark.asyncio
async def test_planned_action_execution_model_tier_is_accepted() -> None:
    """Boundary check: execution-tier actions are eligible for show-notes tooling."""
    fake_llm = _FakeLLMPort([])
    tool_executor = ShowNotesToolExecutor(
        llm=fake_llm,
        config=_config(),
        generator=PropShowNotesGenerator(),
    )
    action = PlannedAction(
        action_id="action-1",
        action_kind=ActionKind.GENERATE_SHOW_NOTES,
        rationale="Hypothesis boundary check for execution tier.",
        model_tier=ModelTier.EXECUTION,
        required_inputs=("script_tei_xml",),
    )

    result = await tool_executor.execute(action, _request())

    assert result.model_tier is ModelTier.EXECUTION
    assert result.summary == "Generated 0 show-notes entries."
