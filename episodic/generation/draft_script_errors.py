"""Exception hierarchy for draft script generation failures.

``DraftScriptGenerationError`` is the base class; the remaining exceptions
distinguish the specific failure modes ``LLMDraftScriptGenerator`` and its
callers must recognise: malformed provider responses, invalid TEI output,
rejected token budgets, and non-retryable or transient provider errors.
"""


class DraftScriptGenerationError(Exception):
    """Base class for draft script generation failures."""


class DraftScriptResponseFormatError(DraftScriptGenerationError, ValueError):
    """Raised when an LLM response does not match the draft schema."""


class DraftScriptTeiError(DraftScriptGenerationError, ValueError):
    """Raised when draft payloads cannot be emitted as valid TEI."""


class DraftScriptTokenBudgetError(DraftScriptGenerationError):
    """Raised when the LLM adapter rejects the draft request budget."""


class DraftScriptProviderResponseError(DraftScriptGenerationError):
    """Raised when the LLM provider returns a non-retryable response error."""


class DraftScriptTransientProviderError(DraftScriptGenerationError):
    """Raised when transient provider failures are exhausted."""
