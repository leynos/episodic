"""Shared helpers for show-notes tests."""

from episodic.llm import LLMRequest, LLMResponse, LLMUsage


class FakeLLMPort:
    """Capture one show-notes request and return a canned response."""

    def __init__(self, response: LLMResponse) -> None:
        self.response = response
        self.requests: list[LLMRequest] = []

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Return the canned response and capture the request."""
        self.requests.append(request)
        return self.response


def valid_llm_response(text: str) -> LLMResponse:
    """Return a valid LLM response for *text*."""
    return LLMResponse(
        text=text,
        model="test-model",
        provider_response_id="test-id",
        finish_reason="stop",
        usage=LLMUsage(input_tokens=10, output_tokens=5, total_tokens=15),
    )
