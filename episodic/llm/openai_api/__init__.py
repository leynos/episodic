"""OpenAI-compatible LLM adapter implementation package.

The package contains the concrete outbound adapter behind the public
`episodic.llm.openai_adapter` facade. `adapter` owns HTTP client lifecycle and
retry orchestration, `request` builds operation-specific provider payloads,
`response` converts OpenAI-compatible responses back into provider-neutral
`LLMResponse` values, and `utils` keeps validation, budget enforcement, and
structured diagnostics in one place.

The modules are intentionally private to the adapter boundary: callers should
depend on `LLMPort`, `OpenAICompatibleLLMAdapter`, and
`OpenAICompatibleLLMConfig`, not on the helper functions in this package.
"""
