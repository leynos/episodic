"""Unit tests for the Pedante factuality evaluator contract."""

from __future__ import annotations

import json
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


def _valid_finding_payload(**overrides: object) -> dict[str, object]:
    """Build a structurally valid finding JSON payload."""
    finding: dict[str, object] = {
        "claim_id": "claim-1",
        "claim_text": "The launch happened in January 2025.",
        "claim_kind": "inference",
        "support_level": "inference_not_supported",
        "severity": "critical",
        "summary": "The cited source does not support this.",
        "remediation": "Remove or cite a supporting source.",
        "cited_source_ids": ["src-1"],
    }
    finding.update(overrides)
    return finding


def _valid_result_payload(**overrides: object) -> dict[str, object]:
    """Build a structurally valid evaluation result payload."""
    payload: dict[str, object] = {
        "summary": "One unsupported claim requires revision.",
        "findings": [_valid_finding_payload()],
    }
    payload.update(overrides)
    return payload


# ── Contract-level validation: PedanteEvaluationRequest ──


def test_pedante_request_rejects_empty_script() -> None:
    """Reject blank TEI payloads at the contract boundary."""
    with pytest.raises(ValueError, match="script_tei_xml"):
        PedanteEvaluationRequest(script_tei_xml="   ", sources=(_source_packet(),))


def test_pedante_request_rejects_empty_sources() -> None:
    """Reject empty sources at the contract boundary."""
    with pytest.raises(ValueError, match="sources"):
        PedanteEvaluationRequest(
            script_tei_xml=(
                "<TEI><text><body><p xml:id='claim-1'>"
                "The policy was announced in March 2024.[Source 1]"
                "</p></body></text></TEI>"
            ),
            sources=(),
        )


# ── Contract-level validation: PedanteSourcePacket ──


@pytest.mark.parametrize(
    "field_name",
    ["source_id", "citation_label", "tei_locator", "title", "excerpt"],
)
def test_pedante_source_packet_rejects_blank_fields(field_name: str) -> None:
    """Reject blank/whitespace-only string fields in PedanteSourcePacket."""
    base_kwargs: dict[str, str] = {
        "source_id": "src-1",
        "citation_label": "Source 1",
        "tei_locator": "//body/div[1]/p[1]",
        "title": "Primary source",
        "excerpt": "The source supports the claim.",
    }
    base_kwargs[field_name] = "   "
    with pytest.raises(ValueError, match=field_name):
        PedanteSourcePacket(**base_kwargs)


# ── Contract-level validation: PedanteEvaluatorConfig ──


def test_pedante_evaluator_config_rejects_blank_model() -> None:
    """Reject blank model in PedanteEvaluatorConfig."""
    with pytest.raises(ValueError, match="model"):
        PedanteEvaluatorConfig(model="   ", system_prompt="You are Pedante.")


def test_pedante_evaluator_config_rejects_blank_system_prompt() -> None:
    """Reject blank system_prompt in PedanteEvaluatorConfig."""
    with pytest.raises(ValueError, match="system_prompt"):
        PedanteEvaluatorConfig(model="gpt-4o-mini", system_prompt="   ")


# ── JSON parsing: basic rejection ──


def test_pedante_parse_result_rejects_invalid_json() -> None:
    """Reject malformed structured output deterministically."""
    with pytest.raises(PedanteResponseFormatError, match="valid JSON object"):
        PedanteEvaluationResult.from_json("not json", usage=LLMUsage(1, 2, 3))


@pytest.mark.parametrize("payload", ["[]", "42", '"string"', "null", "true"])
def test_pedante_parse_result_rejects_non_object_json(payload: str) -> None:
    """Reject syntactically valid JSON that is not a JSON object."""
    with pytest.raises(PedanteResponseFormatError, match="valid JSON object"):
        PedanteEvaluationResult.from_json(payload, usage=LLMUsage(1, 2, 3))


def test_pedante_parse_result_rejects_missing_summary() -> None:
    """Reject payloads with missing or blank summary."""
    usage = LLMUsage(1, 2, 3)
    with pytest.raises(PedanteResponseFormatError, match="summary"):
        PedanteEvaluationResult.from_json(
            json.dumps({"findings": [_valid_finding_payload()]}),
            usage=usage,
        )


def test_pedante_parse_result_rejects_blank_summary() -> None:
    """Reject payloads with blank summary."""
    usage = LLMUsage(1, 2, 3)
    with pytest.raises(PedanteResponseFormatError, match="summary"):
        PedanteEvaluationResult.from_json(
            json.dumps({"summary": "   ", "findings": [_valid_finding_payload()]}),
            usage=usage,
        )


def test_pedante_parse_result_rejects_missing_findings() -> None:
    """Reject payloads with missing findings field."""
    usage = LLMUsage(1, 2, 3)
    with pytest.raises(PedanteResponseFormatError, match="findings"):
        PedanteEvaluationResult.from_json(
            json.dumps({"summary": "Summary."}),
            usage=usage,
        )


@pytest.mark.parametrize(
    "findings_value",
    ["not-a-list", 42, {"not": "a-list"}],
    ids=["string", "integer", "object"],
)
def test_pedante_parse_result_rejects_non_list_findings(
    findings_value: object,
) -> None:
    """Reject findings that are not a list."""
    usage = LLMUsage(1, 2, 3)
    with pytest.raises(PedanteResponseFormatError, match="findings"):
        PedanteEvaluationResult.from_json(
            json.dumps({"summary": "Summary.", "findings": findings_value}),
            usage=usage,
        )


@pytest.mark.parametrize(
    "item",
    [1, "not-an-object", None, True],
    ids=["integer", "string", "null", "boolean"],
)
def test_pedante_parse_result_rejects_non_object_finding_items(
    item: object,
) -> None:
    """Reject findings list items that are not JSON objects."""
    usage = LLMUsage(1, 2, 3)
    with pytest.raises(PedanteResponseFormatError, match="finding must be a JSON"):
        PedanteEvaluationResult.from_json(
            json.dumps({"summary": "Summary.", "findings": [item]}),
            usage=usage,
        )


# ── JSON parsing: enum validation ──


def test_pedante_parse_result_rejects_unknown_support_level() -> None:
    """Reject unsupported finding taxonomy values."""
    with pytest.raises(PedanteResponseFormatError, match="support_level"):
        PedanteEvaluationResult.from_json(
            json.dumps(
                _valid_result_payload(
                    findings=[_valid_finding_payload(support_level="mystery_value")]
                )
            ),
            usage=LLMUsage(5, 7, 12),
        )


@pytest.mark.parametrize(
    ("field_name", "bad_value"),
    [
        ("claim_kind", "not-a-valid-kind"),
        ("severity", "not-a-valid-severity"),
    ],
)
def test_pedante_parse_result_rejects_invalid_enum_values(
    field_name: str,
    bad_value: str,
) -> None:
    """Reject findings with invalid claim_kind or severity values."""
    usage = LLMUsage(1, 2, 3)
    with pytest.raises(PedanteResponseFormatError, match=field_name):
        PedanteEvaluationResult.from_json(
            json.dumps(
                _valid_result_payload(
                    findings=[_valid_finding_payload(**{field_name: bad_value})]
                )
            ),
            usage=usage,
        )


# ── JSON parsing: cited_source_ids validation ──


@pytest.mark.parametrize(
    "bad_ids",
    [
        "not-a-list",
        42,
        [1, 2],
        ["", "src-2"],
        ["   "],
    ],
    ids=[
        "string",
        "integer",
        "non-string-items",
        "empty-string-item",
        "blank-string-item",
    ],
)
def test_pedante_parse_result_rejects_invalid_cited_source_ids(
    bad_ids: object,
) -> None:
    """Reject findings with invalid cited_source_ids field."""
    usage = LLMUsage(1, 2, 3)
    with pytest.raises(PedanteResponseFormatError, match="cited_source_ids"):
        PedanteEvaluationResult.from_json(
            json.dumps(
                _valid_result_payload(
                    findings=[_valid_finding_payload(cited_source_ids=bad_ids)]
                )
            ),
            usage=usage,
        )


# ── Evaluator integration ──


@pytest.mark.asyncio
async def test_pedante_evaluator_returns_typed_findings_and_usage() -> None:
    """Propagate typed findings and normalized usage through the evaluator."""
    llm = _FakeLLMPort(
        LLMResponse(
            text=json.dumps(
                _valid_result_payload(
                    summary="One unsupported claim requires revision.",
                    findings=[
                        _valid_finding_payload(
                            claim_id="claim-1",
                            claim_text="The policy was announced in March 2024.",
                            claim_kind="transplanted_claim",
                            support_level="accurate_restatement",
                            severity="low",
                            summary="The cited source supports the date.",
                            remediation="No change required.",
                        ),
                        _valid_finding_payload(
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


# ── is_blocking and requires_revision ──


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


def test_pedante_requires_revision_false_for_empty_findings() -> None:
    """Empty findings should not require revision."""
    result = PedanteEvaluationResult(
        summary="No issues found.",
        findings=(),
        usage=LLMUsage(10, 5, 15),
    )
    assert result.requires_revision is False


def test_pedante_requires_revision_false_for_non_blocking_findings() -> None:
    """Multiple non-blocking findings should not flip requires_revision."""
    non_blocking_findings = (
        PedanteFinding(
            claim_id="claim-1",
            claim_text="A supported factual statement.",
            claim_kind=ClaimKind.TRANSPLANTED_CLAIM,
            support_level=SupportLevel.ACCURATE_RESTATEMENT,
            severity=FindingSeverity.LOW,
            summary="The claim is fully supported.",
            remediation="No change needed.",
            cited_source_ids=("src-1",),
        ),
        PedanteFinding(
            claim_id="claim-2",
            claim_text="Another supported factual statement.",
            claim_kind=ClaimKind.DIRECT_QUOTE,
            support_level=SupportLevel.ACCURATE_QUOTATION,
            severity=FindingSeverity.LOW,
            summary="The claim is also supported.",
            remediation="No change needed.",
            cited_source_ids=("src-2",),
        ),
    )
    result = PedanteEvaluationResult(
        summary="All claims supported.",
        findings=non_blocking_findings,
        usage=LLMUsage(20, 10, 30),
    )
    assert result.requires_revision is False
