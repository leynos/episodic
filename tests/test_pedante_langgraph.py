"""Unit tests for Pedante's minimal LangGraph seam."""

from __future__ import annotations

import dataclasses as dc
import typing as typ

import pytest

from episodic.llm import LLMUsage
from episodic.qa.langgraph import (
    PedanteGraphState,
    _pedante_node,
    build_pedante_graph,
    route_after_pedante,
)
from episodic.qa.pedante import (
    ClaimKind,
    FindingSeverity,
    PedanteEvaluationRequest,
    PedanteEvaluationResult,
    PedanteFinding,
    PedanteSourcePacket,
    SupportLevel,
)


@dc.dataclass(slots=True)
class _FakePedanteEvaluator:
    """Return one canned Pedante result."""

    result: PedanteEvaluationResult

    async def evaluate(
        self,
        request: PedanteEvaluationRequest,
    ) -> PedanteEvaluationResult:
        """Return the canned result after asserting the graph passed the request."""
        assert request.script_tei_xml.startswith("<TEI>")
        return self.result


def _request() -> PedanteEvaluationRequest:
    return PedanteEvaluationRequest(
        script_tei_xml="<TEI><text><body><p>Claim</p></body></text></TEI>",
        sources=(
            PedanteSourcePacket(
                source_id="src-1",
                citation_label="Source 1",
                tei_locator="//body/div[1]/p[1]",
                title="Primary source",
                excerpt="Claim support excerpt.",
            ),
        ),
    )


def _result(*, blocking: bool) -> PedanteEvaluationResult:
    support_level = (
        SupportLevel.CITATION_ABSENT if blocking else SupportLevel.ACCURATE_RESTATEMENT
    )
    severity = FindingSeverity.HIGH if blocking else FindingSeverity.LOW
    return PedanteEvaluationResult(
        summary="Pedante finished.",
        findings=(
            PedanteFinding(
                claim_id="claim-1",
                claim_text="Claim text.",
                claim_kind=ClaimKind.TRANSPLANTED_CLAIM,
                support_level=support_level,
                severity=severity,
                summary="Finding summary.",
                remediation="Fix the claim.",
                cited_source_ids=("src-1",),
            ),
        ),
        usage=LLMUsage(input_tokens=12, output_tokens=8, total_tokens=20),
        model="gpt-4o-mini",
        provider_response_id="resp-1",
        finish_reason="stop",
    )


@pytest.mark.asyncio
async def test_pedante_graph_routes_supported_scripts_to_pass() -> None:
    """Supported findings should route the graph to the pass branch."""
    graph = build_pedante_graph(_FakePedanteEvaluator(_result(blocking=False)))

    state = await graph.ainvoke(PedanteGraphState(pedante_request=_request()))
    pedante_result = typ.cast("PedanteEvaluationResult", state["pedante_result"])

    assert pedante_result.requires_revision is False


@pytest.mark.asyncio
async def test_pedante_graph_routes_blocking_findings_to_refine() -> None:
    """Blocking findings should route the graph to the refine branch."""
    graph = build_pedante_graph(_FakePedanteEvaluator(_result(blocking=True)))

    state = await graph.ainvoke(PedanteGraphState(pedante_request=_request()))
    pedante_result = typ.cast("PedanteEvaluationResult", state["pedante_result"])

    assert pedante_result.requires_revision is True


def test_route_after_pedante_requires_result() -> None:
    """Routing should fail loudly when graph state is incomplete."""
    with pytest.raises(KeyError, match="pedante_result"):
        route_after_pedante(PedanteGraphState())


def test_route_after_pedante_pass_for_non_blocking() -> None:
    """Non-blocking result should route to pass."""
    state = PedanteGraphState(pedante_result=_result(blocking=False))
    assert route_after_pedante(state) == "pass"


def test_route_after_pedante_refine_for_blocking() -> None:
    """Blocking result should route to refine."""
    state = PedanteGraphState(pedante_result=_result(blocking=True))
    assert route_after_pedante(state) == "refine"


@pytest.mark.asyncio
async def test_pedante_node_requires_pedante_request() -> None:
    """_pedante_node should require a pedante_request in the graph state."""
    evaluator = _FakePedanteEvaluator(_result(blocking=False))
    with pytest.raises(KeyError, match="pedante_request"):
        await _pedante_node(PedanteGraphState(), evaluator=evaluator)
