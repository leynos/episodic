"""Shared fixtures and payload builders for Pedante tests."""

import typing as typ

from episodic.qa.pedante import PedanteEvaluationRequest, PedanteSourcePacket

if typ.TYPE_CHECKING:
    from episodic.llm import LLMRequest, LLMResponse


class FakeLLMPort:
    """Capture one Pedante request and return a canned response."""

    def __init__(self, response: LLMResponse) -> None:
        self.response = response
        self.requests: list[LLMRequest] = []

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Return the canned response and capture the request."""
        self.requests.append(request)
        return self.response


def source_packet(*, source_id: str = "src-1") -> PedanteSourcePacket:
    """Build a valid Pedante source packet."""
    return PedanteSourcePacket(
        source_id=source_id,
        citation_label="Source 1",
        tei_locator="//body/div[@xml:id='src-1']/p[1]",
        title="Primary source",
        excerpt="The source states that the policy was announced in March 2024.",
    )


def evaluation_request() -> PedanteEvaluationRequest:
    """Build a valid Pedante evaluation request."""
    return PedanteEvaluationRequest(
        script_tei_xml=(
            "<TEI><text><body><p xml:id='claim-1'>"
            "The policy was announced in March 2024.[Source 1]"
            "</p></body></text></TEI>"
        ),
        sources=(source_packet(),),
    )


def valid_finding_payload(**overrides: object) -> dict[str, object]:
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


def valid_result_payload(**overrides: object) -> dict[str, object]:
    """Build a structurally valid evaluation result payload."""
    payload: dict[str, object] = {
        "summary": "One unsupported claim requires revision.",
        "findings": [valid_finding_payload()],
    }
    payload.update(overrides)
    return payload
