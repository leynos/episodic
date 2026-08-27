"""Tests for preview configuration credentials and Secret manifests."""

import pytest

from scripts.local_k8s import commands
from scripts.local_k8s.config import PreviewConfig


def test_preview_config_reads_openai_key_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A configured OPENAI_API_KEY reaches the preview configuration."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env-test")

    config = PreviewConfig()

    assert config.openai_api_key == "sk-env-test", (
        "the preview config must read the OpenAI key from the environment"
    )


def test_preview_config_defaults_to_empty_openai_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unset OPENAI_API_KEY defaults to an empty string."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    config = PreviewConfig()

    assert not config.openai_api_key, "the preview config must default to no OpenAI key"


def test_preview_config_reads_openai_base_url_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A configured OPENAI_BASE_URL overrides the provider default."""
    monkeypatch.setenv("OPENAI_BASE_URL", "https://llm.example.test/v1")

    config = PreviewConfig()

    assert config.openai_base_url == "https://llm.example.test/v1", (
        "the preview config must read the provider base URL from the environment"
    )


def test_preview_config_defaults_openai_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unset OPENAI_BASE_URL falls back to the public endpoint."""
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)

    config = PreviewConfig()

    assert config.openai_base_url == "https://api.openai.com/v1", (
        "the preview config must default to the public OpenAI endpoint"
    )


def test_preview_config_repr_hides_the_openai_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The dataclass representation must not expose the API key."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret-value")

    config = PreviewConfig()

    assert "sk-secret-value" not in repr(config), (
        "repr must not expose the OpenAI API key"
    )


def test_secret_manifest_rejects_invalid_namespace() -> None:
    """A namespace outside DNS-1123 rules must fail manifest generation."""
    config = PreviewConfig(namespace="bad\nnamespace: injected")

    with pytest.raises(ValueError, match="namespace must be a DNS-1123 label"):
        commands.secret_manifest(config)


def test_secret_manifest_escapes_newlines_in_values() -> None:
    """Control characters in secret values cannot break out of the scalar."""
    config = PreviewConfig(
        api_bearer_token="line-one\nline-two",  # noqa: S106 - local-only test token.
    )

    manifest = commands.secret_manifest(config)

    assert '"line-one\\nline-two"' in manifest, (
        "newlines must be escaped inside the quoted YAML scalar"
    )
    assert "\nline-two" not in manifest.replace("\\nline-two", ""), (
        "no raw newline from a value may reach the manifest structure"
    )
