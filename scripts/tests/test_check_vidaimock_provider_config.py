"""Provider discovery and configuration failures in the Vidai Mock smoke test."""

from __future__ import annotations

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

    assert str(provider_dir) in str(raised.value), (
        "discovery failures should identify the providers directory"
    )
    assert raised.value.__cause__ is cause, (
        "discovery failures should preserve the filesystem error"
    )


def test_scan_iteration_failure_names_provider_directory_and_preserves_cause(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An error while consuming scandir is translated and closes the iterator."""
    provider_dir = _provider_directory(tmp_path)
    cause = OSError("directory scan interrupted")

    class _ProviderEntry:
        name: str = "openai.yaml"

    class _FailingScan:
        closed = False
        yielded_entry = False

        def __enter__(self) -> _FailingScan:
            return self

        def __exit__(self, *_args: object) -> None:
            self.closed = True

        def __iter__(self) -> _FailingScan:
            return self

        def __next__(self) -> _ProviderEntry:
            if not self.yielded_entry:
                self.yielded_entry = True
                return _ProviderEntry()
            raise cause

    scanner = _FailingScan()

    def fail_during_scan(_path: Path) -> _FailingScan:
        return scanner

    monkeypatch.setattr(smoke.os, "scandir", fail_during_scan)

    with pytest.raises(smoke.SmokeTestError) as raised:
        smoke._configured_provider_names(tmp_path)

    assert str(provider_dir) in str(raised.value), (
        "scan iteration failures should identify the providers directory"
    )
    assert raised.value.__cause__ is cause, (
        "scan iteration failures should preserve the filesystem error"
    )
    assert scanner.closed, "the scandir iterator should close after iteration fails"


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
        assert path == provider_file, "read the discovered provider YAML file"
        raise cause

    monkeypatch.setattr(Path, "read_text", fail_provider_read)

    with pytest.raises(smoke.SmokeTestError) as raised:
        smoke._configured_provider_names(tmp_path)

    assert str(provider_file) in str(raised.value), (
        "read failures should identify the provider file"
    )
    assert raised.value.__cause__ is cause, (
        "read failures should preserve the filesystem error"
    )


@pytest.mark.parametrize(
    ("payload", "expected_cause"),
    [
        pytest.param(
            b"name: \xff\n",
            UnicodeDecodeError,
            id="invalid-utf8",
        ),
        pytest.param(
            b"name: [\n",
            yaml.YAMLError,
            id="malformed-yaml",
        ),
    ],
)
def test_invalid_provider_file_names_path_and_preserves_cause(
    tmp_path: Path,
    payload: bytes,
    expected_cause: type[Exception],
) -> None:
    """Malformed provider bytes retain the path and precise cause type."""
    provider_dir = _provider_directory(tmp_path)
    provider_file = provider_dir / "openai.yaml"
    provider_file.write_bytes(payload)

    with pytest.raises(smoke.SmokeTestError) as raised:
        smoke._configured_provider_names(tmp_path)

    assert str(provider_file) in str(raised.value), (
        "provider file failures should identify the source file"
    )
    assert isinstance(raised.value.__cause__, expected_cause), (
        f"provider file failures should preserve {expected_cause.__name__}"
    )


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

    assert str(provider_file) in str(raised.value), (
        "non-mapping YAML errors should identify the provider file"
    )
    assert raised.value.__cause__ is None, (
        "valid YAML with the wrong shape has no parser error to chain"
    )


def test_missing_provider_name_names_file(tmp_path: Path) -> None:
    """A mapping without its advertised name identifies the source file."""
    provider_dir = _provider_directory(tmp_path)
    provider_file = provider_dir / "openai.yaml"
    provider_file.write_text("matcher: /v1/chat/completions\n", encoding="utf-8")

    with pytest.raises(smoke.SmokeTestError) as raised:
        smoke._configured_provider_names(tmp_path)

    assert str(provider_file) in str(raised.value), (
        "missing provider names should identify the provider file"
    )
    assert "declares no name" in str(raised.value), (
        "missing provider names should explain the invalid mapping"
    )


def test_no_providers_names_directory(tmp_path: Path) -> None:
    """An empty provider directory is reported with its path."""
    provider_dir = _provider_directory(tmp_path)

    with pytest.raises(smoke.SmokeTestError) as raised:
        smoke._configured_provider_names(tmp_path)

    assert str(provider_dir) in str(raised.value), (
        "empty provider discovery should identify the providers directory"
    )
    assert raised.value.__cause__ is None, (
        "an empty directory has no filesystem error to chain"
    )


def test_provider_names_are_sorted_and_yaml_suffix_is_selected(tmp_path: Path) -> None:
    """Declared names are sorted independently of file and scan order."""
    provider_dir = _provider_directory(tmp_path)
    (provider_dir / "z.yaml").write_text("name: zulu\n", encoding="utf-8")
    (provider_dir / "a.yaml").write_text("name: alpha\n", encoding="utf-8")
    (provider_dir / "ignored.yml").write_text("name: ignored\n", encoding="utf-8")
    (provider_dir / "notes.txt").write_text("name: notes\n", encoding="utf-8")

    assert smoke._configured_provider_names(tmp_path) == ["alpha", "zulu"], (
        "provider names should be sorted and non-YAML files ignored"
    )
