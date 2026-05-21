"""Property tests for planner response format errors."""

import json

import hypothesis.strategies as st
import pytest
from hypothesis import given, settings

from episodic.llm import LLMResponse
from episodic.orchestration import (
    GenerationOrchestrationRequest,
    PlanningResponseFormatError,
    StructuredGenerationPlanner,
)
from tests._orchestration_fakes import (
    _config,
    _FakeLLMPort,
    _request,
    _usage,
)
from tests._orchestration_property_support import (
    PLANNER_FORMAT_ERROR_PATTERN,
    invalid_plan_payloads,
)


class TestStructuredGenerationPlannerFormatProperties:
    """Property tests for structured generation planner format validation."""

    @given(
        noise=st.one_of(
            st.integers(),
            st.floats(allow_nan=False, allow_infinity=False),
            st.lists(st.text(max_size=512), max_size=10),
            st.text(max_size=512),
        )
    )
    @settings(max_examples=50)
    @pytest.mark.asyncio
    async def test_planning_response_format_error_for_arbitrary_non_object_json(
        self,
        noise: object,
    ) -> None:
        """Property test: non-object JSON bodies fail strict planner validation."""
        blob = json.dumps(noise)

        response = LLMResponse(
            text=blob,
            model="gpt-4.1",
            provider_response_id="hyp-planner-response",
            finish_reason="stop",
            usage=_usage(input_tokens=1, output_tokens=1),
        )
        planner = StructuredGenerationPlanner(
            llm=_FakeLLMPort([response]),
            config=_config(),
        )
        request = GenerationOrchestrationRequest(
            correlation_id="hyp-corr",
            script_tei_xml="<TEI><body><p>noise</p></body></TEI>",
        )
        with pytest.raises(
            PlanningResponseFormatError,
            match=r"planner response must be an object",
        ):
            await planner.plan(request)

    @given(payload=invalid_plan_payloads)
    @settings(max_examples=100)
    @pytest.mark.asyncio
    async def test_planning_response_format_error_for_invalid_plan_objects(
        self,
        payload: str,
    ) -> None:
        """Property test: structurally invalid plan objects preserve format errors."""
        response = LLMResponse(
            text=payload,
            model="gpt-4.1",
            provider_response_id="hyp-invalid-plan-response",
            finish_reason="stop",
            usage=_usage(input_tokens=1, output_tokens=1),
        )
        planner = StructuredGenerationPlanner(
            llm=_FakeLLMPort([response]),
            config=_config(),
        )

        with pytest.raises(
            PlanningResponseFormatError,
            match=PLANNER_FORMAT_ERROR_PATTERN,
        ):
            await planner.plan(_request())
