"""LLM-backed Pedante evaluator orchestration.

The ``PedanteEvaluator`` class and its response-to-result mapping live here so
the package ``__init__`` only re-exports the public contract.
"""

import dataclasses as dc
import json

from episodic.llm import LLMPort, LLMRequest, LLMResponse

from . import types as pedante_types


@dc.dataclass(slots=True)
class PedanteEvaluator:
    """LLM-backed Pedante evaluator using the provider-neutral LLM port."""

    llm: LLMPort
    config: pedante_types.PedanteEvaluatorConfig

    @staticmethod
    def build_prompt(request: pedante_types.PedanteEvaluationRequest) -> str:
        """Render the Pedante prompt from the TEI-backed request."""
        prompt_payload = {
            "task": (
                "Inspect the TEI P5 script, identify claims, inspect the cited "
                "sources, and assess whether each claim is supported."
            ),
            "support_level_taxonomy": [
                level.value for level in pedante_types.SupportLevel
            ],
            "severity_levels": [
                severity.value for severity in pedante_types.FindingSeverity
            ],
            "claim_kinds": [claim_kind.value for claim_kind in pedante_types.ClaimKind],
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
        request: pedante_types.PedanteEvaluationRequest,
    ) -> pedante_types.PedanteEvaluationResult:
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


def _result_from_response(
    response: LLMResponse,
) -> pedante_types.PedanteEvaluationResult:
    """Parse a provider response into a Pedante evaluation result."""
    parsed = pedante_types.PedanteEvaluationResult.from_json(
        response.text,
        usage=response.usage,
    )
    return dc.replace(
        parsed,
        model=response.model,
        provider_response_id=response.provider_response_id,
        finish_reason=response.finish_reason,
    )
