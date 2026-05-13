"""Validation tests for Pedante request and result contracts."""

import json

import pytest

import tests.test_pedante_support as pedante_support
from episodic.llm import LLMUsage
from episodic.qa.pedante import (
    ClaimKind,
    FindingSeverity,
    PedanteEvaluationRequest,
    PedanteEvaluationResult,
    PedanteEvaluatorConfig,
    PedanteFinding,
    PedanteSourcePacket,
    SupportLevel,
)


def test_pedante_request_rejects_empty_script() -> None:
    """Reject blank TEI payloads at the contract boundary."""
    with pytest.raises(ValueError, match="script_tei_xml"):
        PedanteEvaluationRequest(
            script_tei_xml="   ", sources=(pedante_support.source_packet(),)
        )


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


def test_pedante_evaluator_config_rejects_blank_model() -> None:
    """Reject blank model in PedanteEvaluatorConfig."""
    with pytest.raises(ValueError, match="model"):
        PedanteEvaluatorConfig(model="   ", system_prompt="You are Pedante.")


def test_pedante_evaluator_config_rejects_blank_system_prompt() -> None:
    """Reject blank system_prompt in PedanteEvaluatorConfig."""
    with pytest.raises(ValueError, match="system_prompt"):
        PedanteEvaluatorConfig(model="gpt-4o-mini", system_prompt="   ")


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


def test_pedante_parse_result_allows_empty_findings_list() -> None:
    """Empty findings list in JSON should parse and not require revision."""
    payload = json.dumps({"summary": "No issues found.", "findings": []})
    result = PedanteEvaluationResult.from_json(payload, usage=LLMUsage(10, 5, 15))

    # Keep the tuple contract explicit; truthiness would allow list regressions.
    assert result.findings == (), (  # pylint: disable=use-implicit-booleaness-not-comparison
        f"expected empty tuple for findings, got {result.findings!r} "
        f"({type(result.findings).__name__})"
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
