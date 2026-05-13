"""Shared fixtures for chapter-marker generator tests."""

import asyncio
import typing as typ

from episodic.generation.chapter_markers import (
    ChapterMarkersGenerator,
    ChapterMarkersGeneratorConfig,
)
from episodic.llm import LLMRequest, LLMResponse, LLMUsage


class FakeLLMPort:
    """Capture chapter-marker requests and return a canned response."""

    def __init__(self, response: LLMResponse) -> None:
        self.response = response
        self.requests: list[LLMRequest] = []

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Return the canned response and capture the request."""
        self.requests.append(request)
        return self.response


class BlockingLLMPort:
    """LLM fake that blocks until cancelled by the caller."""

    def __init__(self) -> None:
        self.started = asyncio.Event()

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Block indefinitely so timeout and cancellation behaviour is visible."""
        _ = request
        self.started.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


SEGMENT_STRUCTURE: dict[str, object] = {
    "segments": [
        {"id": "seg-intro", "title": "Introduction", "start": "PT0S"},
        {"id": "seg-main", "title": "Main", "start": "PT5M30S"},
    ]
}


def make_generator(fake_llm: object = None) -> ChapterMarkersGenerator:
    """Build a chapter-marker generator with test configuration."""
    return ChapterMarkersGenerator(
        llm=typ.cast("typ.Any", fake_llm),
        config=ChapterMarkersGeneratorConfig(model="test-model"),
    )


def minimal_tei() -> str:
    """Return a minimal TEI script with two segment locators."""
    return (
        '<TEI xmlns="http://www.tei-c.org/ns/1.0">'
        "<teiHeader><fileDesc><title>Test</title></fileDesc></teiHeader>"
        "<text><body>"
        '<p xml:id="seg-intro">Welcome and framing.</p>'
        '<p xml:id="seg-main">Main discussion.</p>'
        "</body></text>"
        "</TEI>"
    )


def valid_llm_response(text: str) -> LLMResponse:
    """Return a representative successful LLM response."""
    return LLMResponse(
        text=text,
        model="test-model",
        provider_response_id="test-id",
        finish_reason="stop",
        usage=LLMUsage(input_tokens=10, output_tokens=5, total_tokens=15),
    )


def iso_duration(seconds: int) -> str:
    """Format integer seconds as a supported PT duration."""
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    parts = ["PT"]
    if hours:
        parts.append(f"{hours}H")
    if minutes:
        parts.append(f"{minutes}M")
    if secs or seconds == 0:
        parts.append(f"{secs}S")
    return "".join(parts)
