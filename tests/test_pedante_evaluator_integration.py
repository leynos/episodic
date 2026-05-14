"""Evaluator integration tests for Pedante."""

import json

import pytest

import tests.test_pedante_support as pedante_support
from episodic.llm import LLMProviderOperation, LLMResponse, LLMTokenBudget, LLMUsage
from episodic.qa.pedante import (
    ClaimKind,
    FindingSeverity,
    PedanteEvaluationRequest,
    PedanteEvaluationResult,
    PedanteEvaluator,
    PedanteEvaluatorConfig,
    SupportLevel,
)


def _make_evaluator_fixture(
    response_text: str,
) -> tuple[
    PedanteEvaluator,
    PedanteEvaluationRequest,
    pedante_support.FakeLLMPort,
    PedanteEvaluatorConfig,
]:
    """Build a Pedante evaluator with a canned LLM response."""
    request = pedante_support.evaluation_request()
    response = LLMResponse(
        text=response_text,
        model="gpt-4o-mini",
        provider_response_id="resp-1",
        finish_reason="stop",
        usage=LLMUsage(input_tokens=120, output_tokens=55, total_tokens=175),
    )
    port = pedante_support.FakeLLMPort(response)
    config = PedanteEvaluatorConfig(
        model="gpt-4o-mini",
        provider_operation=LLMProviderOperation.CHAT_COMPLETIONS,
        token_budget=LLMTokenBudget(
            max_input_tokens=2048,
            max_output_tokens=2048,
            max_total_tokens=2048,
        ),
        system_prompt="Return JSON only.",
    )
    return PedanteEvaluator(llm=port, config=config), request, port, config


def _assert_expected_request(
    port: pedante_support.FakeLLMPort,
    config: PedanteEvaluatorConfig,
    request: PedanteEvaluationRequest,
) -> None:
    """Assert that Pedante sent the expected LLM request."""
    assert len(port.requests) == 1, f"expected one LLM request, got {port.requests!r}"
    llm_request = port.requests[0]
    assert llm_request.model == config.model, (
        f"unexpected request model: {llm_request.model!r}"
    )
    assert llm_request.provider_operation == config.provider_operation, (
        f"unexpected provider operation: {llm_request.provider_operation!r}"
    )
    assert llm_request.system_prompt == config.system_prompt, (
        f"unexpected system prompt: {llm_request.system_prompt!r}"
    )
    assert "<TEI>" in llm_request.prompt, (
        f"request prompt did not include TEI payload: {llm_request.prompt!r}"
    )
    assert request.script_tei_xml in llm_request.prompt, (
        f"request prompt did not include script XML: {llm_request.prompt!r}"
    )


def _assert_typed_result(result: PedanteEvaluationResult) -> None:
    """Assert that Pedante returned typed findings and provider metadata."""
    assert result.summary == "One unsupported claim requires revision.", (
        f"unexpected result summary: {result.summary!r}"
    )
    assert result.usage == LLMUsage(
        input_tokens=120, output_tokens=55, total_tokens=175
    ), f"unexpected usage: {result.usage!r}"
    assert result.provider_response_id == "resp-1", (
        f"unexpected provider response id: {result.provider_response_id!r}"
    )
    assert result.finish_reason == "stop", (
        f"unexpected finish reason: {result.finish_reason!r}"
    )
    assert result.model == "gpt-4o-mini", f"unexpected result model: {result.model!r}"
    assert tuple(finding.claim_id for finding in result.findings) == (
        "claim-1",
        "claim-2",
    ), f"unexpected finding claim ids: {result.findings!r}"
    second_finding = result.findings[1]
    assert second_finding.claim_kind is ClaimKind.INFERENCE, (
        f"unexpected second finding claim kind: {second_finding.claim_kind!r}"
    )
    assert second_finding.support_level is SupportLevel.INFERENCE_NOT_SUPPORTED, (
        f"unexpected second finding support level: {second_finding.support_level!r}"
    )
    assert second_finding.severity is FindingSeverity.CRITICAL, (
        f"unexpected second finding severity: {second_finding.severity!r}"
    )
    assert second_finding.is_blocking is True, (
        f"expected second finding to be blocking, got {second_finding.is_blocking!r}"
    )
    assert result.requires_revision is True, (
        f"expected result to require revision, got {result.requires_revision!r}"
    )


@pytest.mark.asyncio
async def test_pedante_evaluator_returns_typed_findings_and_usage() -> None:
    """Propagate typed findings and normalized usage through the evaluator."""
    payload = pedante_support.valid_result_payload(
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
                claim_text="The minister confirmed the launch in January 2025.",
                claim_kind="inference",
                support_level="inference_not_supported",
                severity="critical",
                summary="The cited source does not mention a January 2025 launch.",
                remediation="Remove the sentence or cite a supporting source.",
            ),
        ],
    )
    evaluator, request, port, config = _make_evaluator_fixture(json.dumps(payload))

    result = await evaluator.evaluate(request)

    _assert_expected_request(port, config, request)
    _assert_typed_result(result)
