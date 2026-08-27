"""Runtime composition tests for the OPENAI_* provider request options."""

import asyncio
import json
import typing as typ

import httpx
import pytest

if typ.TYPE_CHECKING:
    from pathlib import Path

    from episodic.api.dependencies import ApiDependencies


def _provider_option_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Set the runtime environment carrying the provider request options."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://example.test/episodic")
    monkeypatch.setenv("SOURCE_INTAKE_OBJECT_STORE_ROOT", str(tmp_path))
    monkeypatch.setenv("API_AUTHORIZATION_BEARER_TOKEN", "runtime-test-token")
    monkeypatch.setenv("API_AUTHORIZATION_PRINCIPAL_ID", "runtime-test-principal")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://llm.example.test/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_REASONING_EFFORT", "low")
    monkeypatch.setenv("OPENAI_SERVICE_TIER", "flex")
    monkeypatch.setenv("OPENAI_TOKEN_LIMIT_PARAM", "max_completion_tokens")
    monkeypatch.setenv("OPENAI_TIMEOUT_SECONDS", "600")


def _compose_runtime_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> ApiDependencies:
    """Run create_app_from_env with a stubbed database, capturing dependencies."""
    from unittest import mock

    from episodic.api import runtime as runtime_module
    from episodic.api.dependencies import ApiDependencies

    captured: dict[str, ApiDependencies] = {}

    async def check_database() -> bool:
        await asyncio.sleep(0)
        return True

    async def shutdown_database() -> None:
        await asyncio.sleep(0)

    probe = runtime_module.ReadinessProbe(name="database", check=check_database)

    def capture_dependencies(dependencies: ApiDependencies) -> object:
        captured["dependencies"] = dependencies
        return object()

    with (
        mock.patch.object(
            runtime_module,
            "_build_database_probe",
            return_value=(probe, object, shutdown_database),
        ),
        mock.patch.object(
            runtime_module,
            "create_app",
            side_effect=capture_dependencies,
        ),
    ):
        runtime_module.create_app_from_env()
    dependencies = captured["dependencies"]
    assert isinstance(dependencies, ApiDependencies), (
        f"expected captured ApiDependencies, got {type(dependencies).__name__}"
    )
    return dependencies


def _assert_configured_provider_request(request: httpx.Request) -> None:
    """Assert that the request carries the configured provider options."""
    body = json.loads(request.content.decode())
    assert body["reasoning_effort"] == "low", (
        f"expected reasoning_effort 'low' in the body, got {body!r}"
    )
    assert body["service_tier"] == "flex", (
        f"expected service_tier 'flex' in the body, got {body!r}"
    )
    assert body["max_completion_tokens"] == 2000, (
        f"expected the requested output budget, got {body!r}"
    )
    assert "max_tokens" not in body, (
        "the default token parameter must be replaced, not duplicated"
    )
    timeout = request.extensions["timeout"]
    expected_timeout = dict.fromkeys(("connect", "read", "write", "pool"), 600.0)
    assert timeout == expected_timeout, (
        f"expected a 600 second request timeout, got {timeout!r}"
    )


def test_create_app_from_env_propagates_provider_request_options(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Runtime composition carries the OPENAI_* options into the LLM config."""
    from unittest import mock

    from episodic.api import runtime as runtime_module
    from episodic.llm.openai_adapter import OpenAICompatibleLLMConfig

    _provider_option_environment(monkeypatch, tmp_path)
    with mock.patch.object(
        runtime_module,
        "OpenAICompatibleLLMConfig",
        wraps=OpenAICompatibleLLMConfig,
    ) as config_factory:
        _compose_runtime_dependencies(monkeypatch)

    assert config_factory.call_count == 1, (
        f"expected one constructed LLM config, got {config_factory.call_count}"
    )
    kwargs = config_factory.call_args.kwargs
    assert kwargs["reasoning_effort"] == "low", (
        f"expected reasoning effort 'low', got {kwargs['reasoning_effort']!r}"
    )
    assert kwargs["service_tier"] == "flex", (
        f"expected service tier 'flex', got {kwargs['service_tier']!r}"
    )
    assert kwargs["token_limit_param"] == "max_completion_tokens", (  # noqa: S105 - parameter name, not a secret.
        f"expected max_completion_tokens, got {kwargs['token_limit_param']!r}"
    )
    assert kwargs["timeout_seconds"] == 600.0, (
        f"expected a 600 second timeout, got {kwargs['timeout_seconds']!r}"
    )


@pytest.mark.asyncio
async def test_runtime_composed_adapter_sends_configured_provider_request(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The runtime-created adapter emits the configured provider HTTP request."""
    from episodic.llm import LLMRequest, LLMTokenBudget

    _provider_option_environment(monkeypatch, tmp_path)
    from episodic.llm.openai_adapter import OpenAICompatibleLLMAdapter

    dependencies = _compose_runtime_dependencies(monkeypatch)
    adapter = dependencies.llm_port
    assert isinstance(adapter, OpenAICompatibleLLMAdapter), (
        f"expected a runtime-composed OpenAI adapter, got {type(adapter).__name__}"
    )

    captured_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(request)
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-runtime-wiring",
                "model": "gpt-5.6-sol",
                "choices": [
                    {
                        "message": {"content": "Draft intro copy."},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 12,
                    "completion_tokens": 7,
                    "total_tokens": 19,
                },
            },
        )

    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        await adapter.generate(
            LLMRequest(
                model="gpt-5.6-sol",
                prompt="Draft an intro.",
                token_budget=LLMTokenBudget(
                    max_input_tokens=1000,
                    max_output_tokens=2000,
                    max_total_tokens=3000,
                ),
            )
        )
    finally:
        await dependencies.shutdown_hooks[0]()

    assert len(captured_requests) == 1, (
        f"expected one provider request, got {len(captured_requests)}"
    )
    _assert_configured_provider_request(captured_requests[0])
