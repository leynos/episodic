"""Define the port and implementation for one-pass draft script generation.

The immutable request and result types carry canonical source and presenter
context. ``DraftScriptGenerator`` is the public seam; its LLM implementation
maps provider failures, parses deterministic JSON, and emits TEI-P5 XML with
content hashes and usage metadata.

The launcher maps canonical documents and bindings into a request; generation
persistence stores the result on the canonical episode.

Request/result types, configuration, and the error hierarchy live in
``episodic.generation.draft_script_types`` and
``episodic.generation.draft_script_errors``; prompt building, response
parsing, and TEI emission live in ``episodic.generation.draft_script_parsing``.
This module re-exports them all to preserve the original import path.
"""

import dataclasses as dc
import typing as typ

from episodic.canonical.hashing import sha256_text
from episodic.generation.draft_script_errors import (
    DraftScriptGenerationError,
    DraftScriptProviderResponseError,
    DraftScriptResponseFormatError,
    DraftScriptTeiError,
    DraftScriptTokenBudgetError,
    DraftScriptTransientProviderError,
)
from episodic.generation.draft_script_parsing import (
    _build_prompt,
    _emit_tei,
    _parse_response,
    _require_response_size,
)
from episodic.generation.draft_script_types import (
    DraftPresenterProfile,
    DraftScriptRequest,
    DraftScriptResult,
    DraftScriptSource,
    DraftTurn,
    LLMDraftScriptGeneratorConfig,
)
from episodic.llm import (
    LLMPort,
    LLMProviderResponseError,
    LLMRequest,
    LLMTokenBudgetExceededError,
    LLMTransientProviderError,
)

__all__ = [
    "DraftPresenterProfile",
    "DraftScriptGenerationError",
    "DraftScriptGenerator",
    "DraftScriptProviderResponseError",
    "DraftScriptRequest",
    "DraftScriptResponseFormatError",
    "DraftScriptResult",
    "DraftScriptSource",
    "DraftScriptTeiError",
    "DraftScriptTokenBudgetError",
    "DraftScriptTransientProviderError",
    "DraftTurn",
    "LLMDraftScriptGenerator",
    "LLMDraftScriptGeneratorConfig",
]


class DraftScriptGenerator(typ.Protocol):
    """Protocol implemented by one-pass draft generators."""

    async def generate(self, request: DraftScriptRequest) -> DraftScriptResult:
        """Generate one draft script from canonical generation context.

        Parameters
        ----------
        request
            Immutable canonical generation context.

        Returns
        -------
        DraftScriptResult
            Generated TEI-P5 XML, hash, and provider metadata.

        Raises
        ------
        DraftScriptGenerationError
            If generation cannot produce a valid draft.
        """
        raise NotImplementedError


@dc.dataclass(frozen=True, slots=True)
class LLMDraftScriptGenerator(DraftScriptGenerator):
    """Generate draft TEI scripts through an LLM port and its configuration."""

    llm: LLMPort
    config: LLMDraftScriptGeneratorConfig

    @typ.override
    async def generate(self, request: DraftScriptRequest) -> DraftScriptResult:
        """Generate and validate one TEI-P5 draft script.

        Parameters
        ----------
        request
            Canonical context used to build the deterministic prompt.

        Returns
        -------
        DraftScriptResult
            Validated TEI-P5 XML, hash, usage, and provider metadata.

        Raises
        ------
        DraftScriptTokenBudgetError
            If the LLM adapter rejects the requested token budget.
        DraftScriptProviderResponseError
            If the provider returns a non-retryable response error.
        DraftScriptTransientProviderError
            If the provider reports a transient failure.
        DraftScriptResponseFormatError
            If the provider response is not the expected JSON draft.
        DraftScriptTeiError
            If the parsed draft cannot be emitted as valid TEI-P5.

        Notes
        -----
        Provider errors are translated before parsing and TEI emission.
        """  # noqa: DOC502  # Parsing and TEI helpers raise these documented exceptions.
        llm_request = LLMRequest(
            model=self.config.model,
            prompt=_build_prompt(request),
            system_prompt=self.config.system_prompt,
            provider_operation=self.config.provider_operation,
            token_budget=self.config.token_budget,
        )
        try:
            response = await self.llm.generate(llm_request)
        except LLMTokenBudgetExceededError as exc:
            raise DraftScriptTokenBudgetError(str(exc)) from exc
        except LLMProviderResponseError as exc:
            raise DraftScriptProviderResponseError(str(exc)) from exc
        except LLMTransientProviderError as exc:
            raise DraftScriptTransientProviderError(str(exc)) from exc

        _require_response_size(response.text, self.config.max_response_bytes)
        parsed = _parse_response(response)
        tei_xml = _emit_tei(parsed, request.id_factory)
        return DraftScriptResult(
            tei_xml=tei_xml,
            content_hash=sha256_text(tei_xml),
            usage=response.usage,
            model=response.model,
            provider_response_id=response.provider_response_id,
            finish_reason=response.finish_reason,
            provider_call_usage=response.provider_call_usage,
        )
