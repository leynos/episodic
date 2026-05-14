"""Pedante factuality and accuracy evaluator.

This package implements Pedante, an LLM-backed evaluator that checks whether
claims in TEI P5 podcast scripts are accurately supported by their cited source
material.

Main entry points:

- ``PedanteEvaluator``: The primary evaluator class that orchestrates LLM-based
  factuality assessment. Call ``await evaluator.evaluate(request)`` to analyze a
  script and receive structured findings.
- ``PedanteEvaluationRequest``: Input contract containing the TEI XML script and
  source packets.
- ``PedanteEvaluationResult``: Output contract providing a summary, typed
  findings, LLM usage metadata, and a ``requires_revision`` flag.

The former single module was split under
https://github.com/leynos/episodic/issues/92 into evaluator orchestration,
DTO/enum contracts, and strict JSON parsing helpers.
"""

import dataclasses as dc
import json

from episodic.llm import LLMPort, LLMRequest, LLMResponse

from .types import (
    ClaimKind,
    FindingSeverity,
    PedanteEvaluationRequest,
    PedanteEvaluationResult,
    PedanteEvaluatorConfig,
    PedanteFinding,
    PedanteResponseFormatError,
    PedanteSourcePacket,
    SupportLevel,
)


@dc.dataclass(slots=True)
class PedanteEvaluator:
    """LLM-backed Pedante evaluator using the provider-neutral LLM port."""

    llm: LLMPort
    config: PedanteEvaluatorConfig

    @staticmethod
    def build_prompt(request: PedanteEvaluationRequest) -> str:
        """Render the Pedante prompt from the TEI-backed request."""
        prompt_payload = {
            "task": (
                "Inspect the TEI P5 script, identify claims, inspect the cited "
                "sources, and assess whether each claim is supported."
            ),
            "support_level_taxonomy": [level.value for level in SupportLevel],
            "severity_levels": [severity.value for severity in FindingSeverity],
            "claim_kinds": [claim_kind.value for claim_kind in ClaimKind],
            "script_tei_xml": request.script_tei_xml,
            "sources": [
                {
                    "source_id": source.source_id,
                    "citation_label": source.citation_label,
                    "tei_locator": source.tei_locator,
                    "title": source.title,
                    "excerpt": source.excerpt,
                }
                for source in request.sources
            ],
        }
        rendered_payload = json.dumps(prompt_payload, indent=2, ensure_ascii=True)
        return (
            "Evaluate the following TEI-backed script against its cited source "
            "packets. Return JSON only.\n"
            f"{rendered_payload}"
        )

    async def evaluate(
        self,
        request: PedanteEvaluationRequest,
    ) -> PedanteEvaluationResult:
        """Call the LLM port and parse strict Pedante findings."""
        response = await self.llm.generate(
            LLMRequest(
                model=self.config.model,
                prompt=self.build_prompt(request),
                system_prompt=self.config.system_prompt,
                provider_operation=self.config.provider_operation,
                token_budget=self.config.token_budget,
            )
        )
        return _result_from_response(response)


def _result_from_response(response: LLMResponse) -> PedanteEvaluationResult:
    """Parse a provider response into a Pedante evaluation result."""
    parsed = PedanteEvaluationResult.from_json(
        response.text,
        usage=response.usage,
    )
    return dc.replace(
        parsed,
        model=response.model,
        provider_response_id=response.provider_response_id,
        finish_reason=response.finish_reason,
    )


__all__ = (
    "ClaimKind",
    "FindingSeverity",
    "PedanteEvaluationRequest",
    "PedanteEvaluationResult",
    "PedanteEvaluator",
    "PedanteEvaluatorConfig",
    "PedanteFinding",
    "PedanteResponseFormatError",
    "PedanteSourcePacket",
    "SupportLevel",
)
