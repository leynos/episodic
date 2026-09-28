"""Tests for preview configuration credentials and Secret manifests."""

import pytest
import yaml

from scripts.local_k8s import commands
from scripts.local_k8s.config import PreviewConfig


class TestPreviewConfig:
    """Environment loading and representation rules for preview settings."""

    def test_preview_config_reads_openai_key_from_environment(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A configured OPENAI_API_KEY reaches the preview configuration."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-env-test")

        config = PreviewConfig()

        assert config.openai_api_key == "sk-env-test", (
            "the preview config must read the OpenAI key from the environment"
        )

    def test_preview_config_defaults_to_empty_openai_key(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """An unset OPENAI_API_KEY defaults to an empty string."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        config = PreviewConfig()

        assert not config.openai_api_key, (
            "the preview config must default to no OpenAI key"
        )

    def test_preview_config_reads_openai_base_url_from_environment(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A configured OPENAI_BASE_URL overrides the provider default."""
        monkeypatch.setenv("OPENAI_BASE_URL", "https://llm.example.test/v1")

        config = PreviewConfig()

        assert config.openai_base_url == "https://llm.example.test/v1", (
            "the preview config must read the provider base URL from the environment"
        )

    def test_preview_config_defaults_openai_base_url(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """An unset OPENAI_BASE_URL falls back to the public endpoint."""
        monkeypatch.delenv("OPENAI_BASE_URL", raising=False)

        config = PreviewConfig()

        assert config.openai_base_url == "https://api.openai.com/v1", (
            "the preview config must default to the public OpenAI endpoint"
        )

    def test_preview_config_repr_hides_the_openai_key(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The dataclass representation must not expose the API key."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-secret-value")

        config = PreviewConfig()

        assert "sk-secret-value" not in repr(config), (
            "repr must not expose the OpenAI API key"
        )


class TestSecretManifest:
    """Validation and safe YAML encoding for generated Secrets."""

    def test_secret_manifest_rejects_invalid_namespace(self) -> None:
        """A namespace outside DNS-1123 rules must fail manifest generation."""
        config = PreviewConfig(namespace="bad\nnamespace: injected")

        with pytest.raises(ValueError, match="namespace must be a DNS-1123 label"):
            commands.secret_manifest(config)

    def test_secret_manifest_rejects_trailing_newline_in_name(self) -> None:
        """A final newline cannot pass DNS-1123 validation."""
        invalid_resource_name = "preview\n"
        config = PreviewConfig(secret_name=invalid_resource_name)

        with pytest.raises(ValueError, match="secret_name must be a DNS-1123 label"):
            commands.secret_manifest(config)

    def test_secret_manifest_escapes_newlines_in_values(self) -> None:
        """Control characters stay inside a valid quoted YAML scalar."""
        scalar_value = "line-one\nline-two\x07tail"
        config = PreviewConfig(
            api_bearer_token=scalar_value,
        )

        manifest = commands.secret_manifest(config)
        parsed = yaml.safe_load(manifest)

        assert '"line-one\\nline-two\\u0007tail"' in manifest, (
            "newlines and disallowed YAML controls must be escaped"
        )
        assert parsed["stringData"]["api-bearer-token"] == scalar_value, (
            "YAML decoding must preserve the original secret value"
        )
