"""Provider discovery and configuration failures in the Vidai Mock smoke test."""

from pathlib import Path

import check_vidaimock_isolated as smoke
import pytest
import yaml


def _provider_directory(root: Path) -> Path:
    """Create and return the provider directory under a smoke config root."""
    providers = root / "providers"
    providers.mkdir()
    return providers


def test_discovery_failure_names_provider_directory_and_preserves_cause(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An inaccessible provider directory becomes a path-rich smoke error."""
    provider_dir = _provider_directory(tmp_path)
    cause = PermissionError("directory scan denied")

    def fail_discovery(_path: Path) -> object:
        raise cause

    monkeypatch.setattr(smoke.os, "scandir", fail_discovery)

    with pytest.raises(smoke.SmokeTestError) as raised:
        smoke._configured_provider_names(tmp_path)

    assert str(provider_dir) in str(raised.value)
    assert raised.value.__cause__ is cause


def test_file_read_failure_names_file_and_preserves_cause(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Provider read errors retain the exact path and original exception."""
    provider_dir = _provider_directory(tmp_path)
    provider_file = provider_dir / "openai.yaml"
    provider_file.write_text("name: orchestration\n", encoding="utf-8")
    cause = OSError("file read denied")

    def fail_provider_read(
        path: Path,
        encoding: str | None = None,
        errors: str | None = None,
    ) -> str:
        del encoding, errors
        assert path == provider_file
        raise cause

    monkeypatch.setattr(Path, "read_text", fail_provider_read)

    with pytest.raises(smoke.SmokeTestError) as raised:
        smoke._configured_provider_names(tmp_path)

    assert str(provider_file) in str(raised.value)
    assert raised.value.__cause__ is cause


def test_invalid_utf8_names_file_and_preserves_decode_error(tmp_path: Path) -> None:
    """Invalid UTF-8 is translated while preserving its decoding cause."""
    provider_dir = _provider_directory(tmp_path)
    provider_file = provider_dir / "openai.yaml"
    provider_file.write_bytes(b"name: \xff\n")

    with pytest.raises(smoke.SmokeTestError) as raised:
        smoke._configured_provider_names(tmp_path)

    assert str(provider_file) in str(raised.value)
    assert isinstance(raised.value.__cause__, UnicodeDecodeError)


def test_malformed_yaml_names_file_and_preserves_parse_error(tmp_path: Path) -> None:
    """Malformed YAML is translated with the provider path and YAML cause."""
    provider_dir = _provider_directory(tmp_path)
    provider_file = provider_dir / "openai.yaml"
    provider_file.write_text("name: [\n", encoding="utf-8")

    with pytest.raises(smoke.SmokeTestError) as raised:
        smoke._configured_provider_names(tmp_path)

    assert str(provider_file) in str(raised.value)
    assert isinstance(raised.value.__cause__, yaml.YAMLError)


@pytest.mark.parametrize("yaml_text", ["- orchestration\n", "null\n"])
def test_non_mapping_yaml_names_file(
    tmp_path: Path,
    yaml_text: str,
) -> None:
    """A successfully parsed non-mapping document is a controlled failure."""
    provider_dir = _provider_directory(tmp_path)
    provider_file = provider_dir / "openai.yaml"
    provider_file.write_text(yaml_text, encoding="utf-8")

    with pytest.raises(smoke.SmokeTestError) as raised:
        smoke._configured_provider_names(tmp_path)

    assert str(provider_file) in str(raised.value)
    assert raised.value.__cause__ is None


def test_missing_provider_name_names_file(tmp_path: Path) -> None:
    """A mapping without its advertised name identifies the source file."""
    provider_dir = _provider_directory(tmp_path)
    provider_file = provider_dir / "openai.yaml"
    provider_file.write_text("matcher: /v1/chat/completions\n", encoding="utf-8")

    with pytest.raises(smoke.SmokeTestError) as raised:
        smoke._configured_provider_names(tmp_path)

    assert str(provider_file) in str(raised.value)
    assert "declares no name" in str(raised.value)


def test_no_providers_names_directory(tmp_path: Path) -> None:
    """An empty provider directory is reported with its path."""
    provider_dir = _provider_directory(tmp_path)

    with pytest.raises(smoke.SmokeTestError) as raised:
        smoke._configured_provider_names(tmp_path)

    assert str(provider_dir) in str(raised.value)
    assert raised.value.__cause__ is None


def test_provider_names_are_sorted_and_yaml_suffix_is_selected(tmp_path: Path) -> None:
    """Declared names are sorted independently of file and scan order."""
    provider_dir = _provider_directory(tmp_path)
    (provider_dir / "z.yaml").write_text("name: zulu\n", encoding="utf-8")
    (provider_dir / "a.yaml").write_text("name: alpha\n", encoding="utf-8")
    (provider_dir / "ignored.yml").write_text("name: ignored\n", encoding="utf-8")
    (provider_dir / "notes.txt").write_text("name: notes\n", encoding="utf-8")

    assert smoke._configured_provider_names(tmp_path) == ["alpha", "zulu"]
