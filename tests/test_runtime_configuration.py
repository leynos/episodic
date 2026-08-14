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
    })

    assert config.pricing_snapshot_directory == pricing_directory.resolve(), (
        f"expected configured pricing path, got {config.pricing_snapshot_directory}"
    )


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
