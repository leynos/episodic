"""Tests for preview configuration credentials and Secret manifests."""

import pytest
import yaml

from scripts.local_k8s import commands
from scripts.local_k8s.config import PreviewConfig


class TestPreviewConfig:
    """Environment loading and representation rules for preview settings."""

    @pytest.mark.parametrize(
        ("environment_name", "environment_value", "config_attribute"),
        [
            ("OPENAI_API_KEY", "sk-env-test", "openai_api_key"),
            (
                "OPENAI_BASE_URL",
                "https://llm.example.test/v1",
                "openai_base_url",
            ),
        ],
        ids=("api-key", "base-url"),
    )
    def test_preview_config_reads_openai_settings_from_environment(
        self,
        monkeypatch: pytest.MonkeyPatch,
        environment_name: str,
        environment_value: str,
        config_attribute: str,
    ) -> None:
        """Configured provider settings reach the preview configuration."""
        monkeypatch.setenv(environment_name, environment_value)

        config = PreviewConfig()

        assert getattr(config, config_attribute) == environment_value, (
            f"{environment_name} must populate {config_attribute}"
        )

    @pytest.mark.parametrize(
        ("environment_name", "config_attribute", "default_value"),
        [
            ("OPENAI_API_KEY", "openai_api_key", ""),
            (
                "OPENAI_BASE_URL",
                "openai_base_url",
                "https://api.openai.com/v1",
            ),
        ],
        ids=("api-key", "base-url"),
    )
    def test_preview_config_defaults_openai_settings(
        self,
        monkeypatch: pytest.MonkeyPatch,
        environment_name: str,
        config_attribute: str,
        default_value: str,
    ) -> None:
        """Unset provider settings use their documented defaults."""
        monkeypatch.delenv(environment_name, raising=False)

        config = PreviewConfig()

        assert getattr(config, config_attribute) == default_value, (
            f"{environment_name} must default {config_attribute}"
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
