"""Support for the no-QA source-to-script behavioural slice."""

from __future__ import annotations

import dataclasses as dc
import json
import subprocess  # noqa: S404 - terminates a controlled local test process.
import typing as typ

import httpx

from episodic.api import create_app
from episodic.generation import InProcessGenerationRunLauncher
from episodic.generation.draft_script import (
    LLMDraftScriptGenerator,
    LLMDraftScriptGeneratorConfig,
)
from episodic.llm.openai_adapter import (
    OpenAICompatibleLLMAdapter,
    OpenAICompatibleLLMConfig,
)
from tests.fixtures.api import build_api_dependencies
from tests.steps.generation_orchestration_vidaimock import (
    find_free_port,
    start_vidaimock_process,
)

if typ.TYPE_CHECKING:
    import asyncio
    import collections.abc as cabc
    from pathlib import Path

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from episodic.api.dependencies import ApiDependencies


RunResult = typ.TypeVar("RunResult")

_VALID_DRAFT = json.dumps({
    "title": "A deterministic no-QA draft",
    "turns": [
        {"speaker": "host", "text": "Welcome to the generated episode."},
        {"speaker": "guest", "text": "The source supports this discussion."},
    ],
})


@dc.dataclass(slots=True)
class NoQaGenerationSliceContext:
    """Hold infrastructure and observations for one behavioural scenario."""

    session_factory: async_sessionmaker[AsyncSession]
    runner: asyncio.Runner
    process: subprocess.Popen[str] | None = None
    base_url: str = ""
    dependencies: ApiDependencies | None = None
    launcher: InProcessGenerationRunLauncher | None = None
    llm_adapter: OpenAICompatibleLLMAdapter | None = None
    llm_client: httpx.AsyncClient | None = None
    profile_id: str | None = None
    ingestion_job_id: str | None = None
    responses: list[httpx.Response] = dc.field(default_factory=list)
    run_response: httpx.Response | None = None
    events_response: httpx.Response | None = None
    tei_response: httpx.Response | None = None

    def run(self, operation: cabc.Awaitable[RunResult]) -> RunResult:
        """Run an asynchronous scenario operation on the shared event loop."""
        return self.runner.run(operation)

    async def request(
        self,
        method: str,
        path: str,
        *,
        headers: cabc.Mapping[str, str] | None = None,
        json: object | None = None,
    ) -> httpx.Response:
        """Issue one request against the in-process Falcon application."""
        dependencies = require(self.dependencies, "API dependencies")
        transport = httpx.ASGITransport(
            app=typ.cast("typ.Any", create_app(dependencies))
        )
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            return await client.request(method, path, headers=headers, json=json)

    async def close(self) -> None:
        """Release asynchronous resources owned by the scenario."""
        if self.launcher is not None:
            await self.launcher.drain()
            await self.launcher.shutdown()
        if self.llm_adapter is not None:
            await self.llm_adapter.aclose()

    def tear_down(self) -> None:
        """Release asynchronous resources and stop the Vidai Mock process."""
        self.run(self.close())
        if self.process is None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)


def require[RequiredValue](
    value: RequiredValue | None,
    label: str,
) -> RequiredValue:
    """Return initialized scenario state or fail with a useful assertion."""
    assert value is not None, f"Expected {label} to be initialized."
    return value


def configure_vidaimock(context: NoQaGenerationSliceContext, tmp_path: Path) -> None:
    """Start Vidai Mock and wire the real generator and launcher to it."""
    provider_dir = tmp_path / "providers"
    template_dir = tmp_path / "templates" / "draft"
    provider_dir.mkdir(parents=True)
    template_dir.mkdir(parents=True)
    _write_provider_config(provider_dir)
    _write_response_template(template_dir)
    start_vidaimock_process(context, tmp_path, port=find_free_port())

    context.llm_client = httpx.AsyncClient()
    context.llm_adapter = OpenAICompatibleLLMAdapter(
        config=OpenAICompatibleLLMConfig(
            base_url=context.base_url,
            api_key="test-key",
            max_attempts=1,
        ),
        client=context.llm_client,
    )
    context.launcher = InProcessGenerationRunLauncher(
        uow_factory=lambda: build_api_dependencies(
            context.session_factory
        ).uow_factory(),
        draft_generator=LLMDraftScriptGenerator(
            llm=context.llm_adapter,
            config=LLMDraftScriptGeneratorConfig(model="valid-draft"),
        ),
    )
    context.dependencies = dc.replace(
        build_api_dependencies(context.session_factory),
        launcher=context.launcher,
    )


def select_malformed_completion(context: NoQaGenerationSliceContext) -> None:
    """Select the deterministic malformed provider response."""
    adapter = require(context.llm_adapter, "LLM adapter")
    launcher = require(context.launcher, "generation launcher")
    launcher.draft_generator = LLMDraftScriptGenerator(
        llm=adapter,
        config=LLMDraftScriptGeneratorConfig(model="malformed-draft"),
    )


def enable_provider_failure(context: NoQaGenerationSliceContext) -> None:
    """Force Vidai Mock to drop every provider request."""
    client = require(context.llm_client, "LLM HTTP client")
    client.headers["X-Vidai-Chaos-Drop"] = "100"


def generation_payload(**overrides: object) -> dict[str, object]:
    """Return the canonical no-QA creation request."""
    payload: dict[str, object] = {
        "quality_mode": "draft_without_qa",
        "skip_qa_rationale": "Prepare an editorial draft before QA.",
        "actor": "editor@example.com",
    }
    payload.update(overrides)
    return payload


def _write_provider_config(provider_dir: Path) -> None:
    (provider_dir / "draft.yaml").write_text(
        "\n".join((
            'name: "draft"',
            'matcher: "/v1/chat/completions"',
            "request_mapping:",
            '  model: "{{ json.model }}"',
            'response_template: "draft/response.json.j2"',
        ))
        + "\n",
        encoding="utf-8",
    )


def _write_response_template(template_dir: Path) -> None:
    valid_content = json.dumps(_VALID_DRAFT)
    invalid_tei_draft = json.dumps({
        "title": "Invalid TEI draft",
        "turns": [{"speaker": "\u0001", "text": "Invalid XML speaker."}],
    })
    malformed_content = json.dumps(invalid_tei_draft)
    (template_dir / "response.json.j2").write_text(
        f"""{{
  "id": "chatcmpl-{{{{ uuid() }}}}",
  "created": {{{{ timestamp() }}}},
  "object": "chat.completion",
  "model": "{{{{ model }}}}",
  "choices": [{{"index": 0, "message": {{"role": "assistant", "content":
    {{% if model == "malformed-draft" %}}{malformed_content}
    {{% else %}}{valid_content}{{% endif %}}
  }}, "finish_reason": "stop"}}],
  "usage": {{"prompt_tokens": 20, "completion_tokens": 12, "total_tokens": 32}}
}}
""",
        encoding="utf-8",
    )
