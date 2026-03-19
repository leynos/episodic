"""Unit tests for the Pedante factuality evaluator contract."""

from __future__ import annotations

import typing as typ

import pytest

from episodic.llm import (
    LLMProviderOperation,
    LLMRequest,
    LLMResponse,
    LLMUsage,
)
from episodic.qa.pedante import (
    ClaimKind,
    FindingSeverity,
    PedanteEvaluationRequest,
    PedanteEvaluationResult,
    PedanteEvaluator,
    PedanteEvaluatorConfig,
    PedanteFinding,
    PedanteResponseFormatError,
    PedanteSourcePacket,
    SupportLevel,
)


class _FakeLLMPort:
    """Capture one Pedante request and return a canned response."""

    def __init__(self, response: LLMResponse) -> None:
        self.response = response
        self.requests: list[LLMRequest] = []

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Return the canned response and capture the request."""
        self.requests.append(request)
        return self.response


def _source_packet(*, source_id: str = "src-1") -> PedanteSourcePacket:
    return PedanteSourcePacket(
        source_id=source_id,
        citation_label="Source 1",
        tei_locator="//body/div[@xml:id='src-1']/p[1]",
        title="Primary source",
        excerpt="The source states that the policy was announced in March 2024.",
    )


def _evaluation_request() -> PedanteEvaluationRequest:
    return PedanteEvaluationRequest(
        script_tei_xml=(
            "<TEI><text><body><p xml:id='claim-1'>"
            "The policy was announced in March 2024.[Source 1]"
            "</p></body></text></TEI>"
        ),
        sources=(_source_packet(),),
    )


def test_pedante_request_rejects_empty_script() -> None:
    """Reject blank TEI payloads at the contract boundary."""
    with pytest.raises(ValueError, match="script_tei_xml"):
        PedanteEvaluationRequest(script_tei_xml="   ", sources=(_source_packet(),))


def test_pedante_parse_result_rejects_invalid_json() -> None:
    """Reject malformed structured output deterministically."""
    with pytest.raises(PedanteResponseFormatError, match="valid JSON object"):
        PedanteEvaluationResult.from_json("not json", usage=LLMUsage(1, 2, 3))


def test_pedante_parse_result_rejects_unknown_support_level() -> None:
    """Reject unsupported finding taxonomy values."""
    with pytest.raises(PedanteResponseFormatError, match="support_level"):
        PedanteEvaluationResult.from_json(
            """
            {
              "summary": "Unsupported claim detected.",
              "findings": [
                {
                  "claim_id": "claim-1",
                  "claim_text": "The claim text.",
                  "claim_kind": "direct_quote",
                  "support_level": "mystery_value",
                  "severity": "high",
                  "summary": "Unsupported.",
                  "remediation": "Fix it.",
                  "cited_source_ids": ["src-1"]
                }
              ]
            }
            """,
            usage=LLMUsage(5, 7, 12),
        )


@pytest.mark.asyncio
async def test_pedante_evaluator_returns_typed_findings_and_usage() -> None:
    """Propagate typed findings and normalized usage through the evaluator."""
    llm = _FakeLLMPort(
        LLMResponse(
            text="""
            {
              "summary": "One unsupported claim requires revision.",
              "findings": [
                {
                  "claim_id": "claim-1",
                  "claim_text": "The policy was announced in March 2024.",
                  "claim_kind": "transplanted_claim",
                  "support_level": "accurate_restatement",
                  "severity": "low",
                  "summary": "The cited source supports the date.",
                  "remediation": "No change required.",
                  "cited_source_ids": ["src-1"]
                },
                {
                  "claim_id": "claim-2",
                  "claim_text": "The minister confirmed the launch in January 2025.",
                  "claim_kind": "inference",
                  "support_level": "inference_not_supported",
                  "severity": "critical",
                  "summary": "The cited source does not mention a January 2025 launch.",
                  "remediation": "Remove the sentence or cite a supporting source.",
                  "cited_source_ids": ["src-1"]
                }
              ]
            }
            """,
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

    result = await evaluator.evaluate(_evaluation_request())

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


def test_pedante_finding_blocking_property_follows_support_level() -> None:
    """Blocking status should track support failures, not prose wording."""
    assert (
        PedanteFinding(
            claim_id="claim-1",
            claim_text="The quoted text is wrong.",
            claim_kind=ClaimKind.DIRECT_QUOTE,
            support_level=SupportLevel.MISQUOTATION,
            severity=FindingSeverity.CRITICAL,
            summary="The quotation is inaccurate.",
            remediation="Correct the quotation.",
            cited_source_ids=("src-1",),
        ).is_blocking
        is True
    )
    assert (
        PedanteFinding(
            claim_id="claim-2",
            claim_text="A supported paraphrase.",
            claim_kind=ClaimKind.TRANSPLANTED_CLAIM,
            support_level=SupportLevel.ACCURATE_RESTATEMENT,
            severity=FindingSeverity.LOW,
            summary="Supported.",
            remediation="No change required.",
            cited_source_ids=("src-1",),
        ).is_blocking
        is False
    )
