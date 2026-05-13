"""Evaluator integration tests for Pedante."""

import json
import typing as typ

import pytest

import tests.test_pedante_support as pedante_support
from episodic.llm import LLMProviderOperation, LLMResponse, LLMUsage
from episodic.qa.pedante import (
    FindingSeverity,
    PedanteEvaluator,
    PedanteEvaluatorConfig,
    SupportLevel,
)


@pytest.mark.asyncio
async def test_pedante_evaluator_returns_typed_findings_and_usage() -> None:
    """Propagate typed findings and normalized usage through the evaluator."""
    llm = pedante_support.FakeLLMPort(
        LLMResponse(
            text=json.dumps(
                pedante_support.valid_result_payload(
                    summary="One unsupported claim requires revision.",
                    findings=[
                        pedante_support.valid_finding_payload(
                            claim_id="claim-1",
                            claim_text="The policy was announced in March 2024.",
                            claim_kind="transplanted_claim",
                            support_level="accurate_restatement",
                            severity="low",
                            summary="The cited source supports the date.",
                            remediation="No change required.",
                        ),
                        pedante_support.valid_finding_payload(
                            claim_id="claim-2",
                            claim_text=(
                                "The minister confirmed the launch in January 2025."
                            ),
                            claim_kind="inference",
                            support_level="inference_not_supported",
                            severity="critical",
                            summary=(
                                "The cited source does not mention"
                                " a January 2025 launch."
                            ),
                            remediation=(
                                "Remove the sentence or cite a supporting source."
                            ),
                        ),
                    ],
                )
            ),
            model="gpt-4o-mini",
            provider_response_id="resp-1",
            finish_reason="stop",
            usage=LLMUsage(input_tokens=120, output_tokens=55, total_tokens=175),
        )
    )
    evaluator = PedanteEvaluator(
        llm=llm,
        config=PedanteEvaluatorConfig(
            model="gpt-4o-mini",
            provider_operation=LLMProviderOperation.CHAT_COMPLETIONS,
        ),
    )

    result = await evaluator.evaluate(pedante_support.evaluation_request())

    assert len(llm.requests) == 1
    assert llm.requests[0].model == "gpt-4o-mini"
    assert llm.requests[0].provider_operation == LLMProviderOperation.CHAT_COMPLETIONS
    assert "return JSON" in typ.cast("str", llm.requests[0].system_prompt)
    assert "<TEI>" in llm.requests[0].prompt

    assert result.summary == "One unsupported claim requires revision."
    assert result.usage == LLMUsage(
        input_tokens=120, output_tokens=55, total_tokens=175
    )
    assert result.provider_response_id == "resp-1"
    assert result.model == "gpt-4o-mini"
    assert tuple(finding.claim_id for finding in result.findings) == (
        "claim-1",
        "claim-2",
    )
    assert result.findings[1].support_level is SupportLevel.INFERENCE_NOT_SUPPORTED
    assert result.findings[1].severity is FindingSeverity.CRITICAL
    assert result.requires_revision is True
