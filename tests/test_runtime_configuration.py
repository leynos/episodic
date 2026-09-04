"""Focused runtime configuration tests."""

import typing as typ

import pytest

from episodic.api.runtime import RuntimeConfigurationError, _load_runtime_config
from episodic.generation import GenerationSourceLimits

if typ.TYPE_CHECKING:
    from pathlib import Path


def _base_environment(tmp_path: Path) -> dict[str, str]:
    """Return the minimal environment that boots the runtime configuration."""
    pricing_directory = tmp_path / "pricing"
    pricing_directory.mkdir(exist_ok=True)
    return {
        "DATABASE_URL": "postgresql://example.test/episodic",
        "SOURCE_INTAKE_OBJECT_STORE_ROOT": str(tmp_path / "objects"),
        "PRICING_SNAPSHOT_DIRECTORY": str(pricing_directory),
        "API_AUTHORIZATION_BEARER_TOKEN": "test-token",
        "API_AUTHORIZATION_PRINCIPAL_ID": "test-principal",
    }


def test_load_runtime_config_uses_configured_pricing_directory(
    tmp_path: Path,
) -> None:
    """Pricing snapshots should be loaded from a validated configured directory."""
    config = _load_runtime_config({
        **_base_environment(tmp_path),
        "GENERATION_MAX_SOURCE_COUNT": "3",
        "GENERATION_MAX_SOURCE_BYTES": "400",
        "GENERATION_MAX_AGGREGATE_SOURCE_BYTES": "800",
        "GENERATION_MAX_NORMALIZED_SOURCE_BYTES": "200",
        "GENERATION_MAX_OUTPUT_TOKENS": "512",
        "GENERATION_MAX_RESPONSE_BYTES": "4096",
    })

    assert config.pricing_snapshot_directory == (tmp_path / "pricing").resolve(), (
        f"expected configured pricing path, got {config.pricing_snapshot_directory}"
    )
    assert config.generation_source_limits.max_source_count == 3, (
        "expected configured source count 3, got "
        f"{config.generation_source_limits.max_source_count}"
    )
    assert config.generation_source_limits.max_source_bytes == 400, (
        "expected configured source bytes 400, got "
        f"{config.generation_source_limits.max_source_bytes}"
    )
    assert config.generation_source_limits.max_aggregate_source_bytes == 800, (
        "expected configured aggregate source bytes 800, got "
        f"{config.generation_source_limits.max_aggregate_source_bytes}"
    )
    assert config.generation_source_limits.max_normalized_source_bytes == 200, (
        "expected configured normalized source bytes 200, got "
        f"{config.generation_source_limits.max_normalized_source_bytes}"
    )
    assert config.generation_max_output_tokens == 512, (
        "expected configured output token limit 512, got "
        f"{config.generation_max_output_tokens}"
    )
    assert config.generation_max_response_bytes == 4096, (
        "expected configured response limit 4096, got "
        f"{config.generation_max_response_bytes}"
    )


def test_load_runtime_config_applies_declared_defaults(tmp_path: Path) -> None:
    """Optional provider and limit settings fall back to declared defaults."""
    config = _load_runtime_config(_base_environment(tmp_path))

    assert config.draft_model == "gpt-4o-mini", (
        f"expected the default draft model, got {config.draft_model!r}"
    )
    assert config.llm_base_url is None, (
        f"expected no provider base URL by default, got {config.llm_base_url!r}"
    )
    assert config.llm_api_key is None, "expected no provider API key by default"
    defaults = GenerationSourceLimits()
    assert config.generation_source_limits == defaults, (
        f"expected declared source-limit defaults {defaults!r}, got "
        f"{config.generation_source_limits!r}"
    )
    assert config.generation_max_output_tokens == 4_096, (
        "expected the declared default output-token limit, got "
        f"{config.generation_max_output_tokens}"
    )
    assert config.generation_max_response_bytes == 1_048_576, (
        "expected the declared default response-byte limit, got "
        f"{config.generation_max_response_bytes}"
    )


def test_load_runtime_config_rejects_unpaired_openai_base_url(
    tmp_path: Path,
) -> None:
    """A provider base URL without an API key must fail configuration."""
    with pytest.raises(
        RuntimeConfigurationError,
        match="OPENAI_BASE_URL and OPENAI_API_KEY must be configured together",
    ):
        _load_runtime_config({
            **_base_environment(tmp_path),
            "OPENAI_BASE_URL": "https://api.openai.example/v1",
        })


@pytest.mark.parametrize(
    ("setting", "value"),
    [
        ("GENERATION_MAX_SOURCE_COUNT", "0"),
        ("GENERATION_MAX_SOURCE_COUNT", "-1"),
        ("GENERATION_MAX_SOURCE_COUNT", "not-an-integer"),
        ("GENERATION_MAX_OUTPUT_TOKENS", "0"),
        ("GENERATION_MAX_RESPONSE_BYTES", "0"),
    ],
)
def test_load_runtime_config_rejects_invalid_generation_limit(
    tmp_path: Path,
    setting: str,
    value: str,
) -> None:
    """Generation limits must be positive integer runtime settings."""
    with pytest.raises(
        RuntimeConfigurationError,
        match=f"{setting} must be a positive integer",
    ):
        _load_runtime_config({
            **_base_environment(tmp_path),
            setting: value,
        })


def test_load_runtime_config_rejects_missing_pricing_directory(
    tmp_path: Path,
) -> None:
    """Pricing configuration should fail before launcher construction."""
    with pytest.raises(RuntimeConfigurationError, match="PRICING_SNAPSHOT_DIRECTORY"):
        _load_runtime_config({
            "DATABASE_URL": "postgresql://example.test/episodic",
            "SOURCE_INTAKE_OBJECT_STORE_ROOT": str(tmp_path / "objects"),
            "PRICING_SNAPSHOT_DIRECTORY": str(tmp_path / "missing"),
        })


@pytest.mark.parametrize(
    "missing_setting",
    ["DATABASE_URL", "SOURCE_INTAKE_OBJECT_STORE_ROOT"],
)
def test_load_runtime_config_failure_does_not_log_success(
    tmp_path: Path,
    missing_setting: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A failed load must not emit the runtime_config_loaded success line."""
    environment = _base_environment(tmp_path)
    del environment[missing_setting]

    with (
        caplog.at_level("INFO"),
        pytest.raises(RuntimeConfigurationError, match=missing_setting),
    ):
        _load_runtime_config(environment)

    assert "runtime_config_loaded" not in caplog.text, (
        "the success log line must not be emitted for invalid configuration"
    )


def test_load_runtime_config_loads_provider_request_options(
    tmp_path: Path,
) -> None:
    """Configured OPENAI_* request options reach the runtime configuration."""
    config = _load_runtime_config({
        **_base_environment(tmp_path),
        "OPENAI_REASONING_EFFORT": "low",
        "OPENAI_SERVICE_TIER": "flex",
        "OPENAI_TOKEN_LIMIT_PARAM": "max_completion_tokens",
        "OPENAI_TIMEOUT_SECONDS": "600",
    })

    assert config.llm_reasoning_effort == "low", (
        f"expected the configured reasoning effort, got {config.llm_reasoning_effort!r}"
    )
    assert config.llm_service_tier == "flex", (
        f"expected the configured service tier, got {config.llm_service_tier!r}"
    )
    assert config.llm_token_limit_param == "max_completion_tokens", (  # noqa: S105 - parameter name, not a secret.
        f"expected the configured token parameter, got {config.llm_token_limit_param!r}"
    )
    assert config.llm_timeout_seconds == 600.0, (
        f"expected the configured timeout, got {config.llm_timeout_seconds!r}"
    )


def test_load_runtime_config_rejects_unknown_token_limit_param(
    tmp_path: Path,
) -> None:
    """Unknown token-limit parameter names fail configuration."""
    with pytest.raises(
        RuntimeConfigurationError,
        match="OPENAI_TOKEN_LIMIT_PARAM must be max_tokens or",
    ):
        _load_runtime_config({
            **_base_environment(tmp_path),
            "OPENAI_TOKEN_LIMIT_PARAM": "max_words",
        })


@pytest.mark.parametrize("value", ["0", "-3", "abc", "inf", "nan"])
def test_load_runtime_config_rejects_invalid_timeout(
    tmp_path: Path,
    value: str,
) -> None:
    """The provider timeout must be a positive, finite number of seconds."""
    with pytest.raises(
        RuntimeConfigurationError,
        match="OPENAI_TIMEOUT_SECONDS must be a positive number",
    ):
        _load_runtime_config({
            **_base_environment(tmp_path),
            "OPENAI_TIMEOUT_SECONDS": value,
        })
