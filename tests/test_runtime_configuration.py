"""Focused runtime configuration tests."""

import typing as typ

import pytest

if typ.TYPE_CHECKING:
    from pathlib import Path


def test_load_runtime_config_uses_configured_pricing_directory(
    tmp_path: "Path",  # noqa: UP037  # Imported only during type checking.
) -> None:
    """Pricing snapshots should be loaded from a validated configured directory."""
    from episodic.api.runtime import _load_runtime_config

    pricing_directory = tmp_path / "pricing"
    pricing_directory.mkdir()
    config = _load_runtime_config({
        "DATABASE_URL": "postgresql://example.test/episodic",
        "SOURCE_INTAKE_OBJECT_STORE_ROOT": str(tmp_path / "objects"),
        "PRICING_SNAPSHOT_DIRECTORY": str(pricing_directory),
        "API_AUTHORIZATION_BEARER_TOKEN": "test-token",
        "API_AUTHORIZATION_PRINCIPAL_ID": "test-principal",
        "GENERATION_MAX_SOURCE_COUNT": "3",
        "GENERATION_MAX_SOURCE_BYTES": "400",
        "GENERATION_MAX_AGGREGATE_SOURCE_BYTES": "800",
        "GENERATION_MAX_NORMALIZED_SOURCE_BYTES": "200",
    })

    assert config.pricing_snapshot_directory == pricing_directory.resolve(), (
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


@pytest.mark.parametrize("value", ["0", "-1", "not-an-integer"])
def test_load_runtime_config_rejects_invalid_generation_source_limit(
    tmp_path: "Path",  # noqa: UP037  # Imported only during type checking.
    value: str,
) -> None:
    """Generation source limits must be positive integer runtime settings."""
    from episodic.api.runtime import RuntimeConfigurationError, _load_runtime_config

    pricing_directory = tmp_path / "pricing"
    pricing_directory.mkdir()
    with pytest.raises(
        RuntimeConfigurationError,
        match="GENERATION_MAX_SOURCE_COUNT must be a positive integer",
    ):
        _load_runtime_config({
            "DATABASE_URL": "postgresql://example.test/episodic",
            "SOURCE_INTAKE_OBJECT_STORE_ROOT": str(tmp_path / "objects"),
            "PRICING_SNAPSHOT_DIRECTORY": str(pricing_directory),
            "API_AUTHORIZATION_BEARER_TOKEN": "test-token",
            "API_AUTHORIZATION_PRINCIPAL_ID": "test-principal",
            "GENERATION_MAX_SOURCE_COUNT": value,
        })


def test_load_runtime_config_rejects_missing_pricing_directory(
    tmp_path: "Path",  # noqa: UP037  # Imported only during type checking.
) -> None:
    """Pricing configuration should fail before launcher construction."""
    from episodic.api.runtime import RuntimeConfigurationError, _load_runtime_config

    with pytest.raises(RuntimeConfigurationError, match="PRICING_SNAPSHOT_DIRECTORY"):
        _load_runtime_config({
            "DATABASE_URL": "postgresql://example.test/episodic",
            "SOURCE_INTAKE_OBJECT_STORE_ROOT": str(tmp_path / "objects"),
            "PRICING_SNAPSHOT_DIRECTORY": str(tmp_path / "missing"),
        })
