"""Shared callable aliases for OpenAI adapter test fixtures."""

import collections.abc as cabc
import contextlib
import typing as typ

import httpx

from episodic.llm import LLMRequest
from episodic.llm.openai_adapter import (
    OpenAICompatibleLLMAdapter,
    OpenAICompatibleLLMConfig,
)

type _OpenAIAdapterFactory = cabc.Callable[
    ...,
    contextlib.AbstractAsyncContextManager[OpenAICompatibleLLMAdapter],
]
type _OpenAIInvalidConfigBuilder = cabc.Callable[
    [dict[str, object]],
    OpenAICompatibleLLMConfig,
]
type _OpenAIJsonResponseBuilder = cabc.Callable[..., httpx.Response]
type _OpenAIRequestBuilder = cabc.Callable[..., LLMRequest]


class _OpenAILogSpy(typ.Protocol):
    """Captured OpenAI adapter log records for observability tests."""

    messages: list[str]
