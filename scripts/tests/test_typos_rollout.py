"""Tests for the repository spelling-policy scripts."""

import ast
import dataclasses as dc
import email.message
import importlib
import json
import os
import stat
import sys
import tomllib
import types
import typing as typ
import urllib.error
import urllib.request
from pathlib import Path

import pytest

SCRIPT_DIRECTORY = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.append(str(SCRIPT_DIRECTORY))

import atomic_write  # noqa: E402 - path set above for the sibling script.


def test_rollout_scripts_support_python_313() -> None:
    """Every rollout script parses with the declared minimum Python version."""
    for script in SCRIPT_DIRECTORY.glob("*.py"):
        ast.parse(
            script.read_text(encoding="utf-8"),
            filename=str(script),
            feature_version=(3, 13),
        )


@pytest.fixture(name="rollout_modules")
def rollout_modules_fixture(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[types.ModuleType, types.ModuleType, types.ModuleType]:
    """Import the scripts through the same top-level module path used at runtime."""
    monkeypatch.syspath_prepend(str(SCRIPT_DIRECTORY))
    names = ("typos_rollout_cache", "typos_rollout", "generate_typos_config")
    importlib.invalidate_caches()
    cache, rollout, generator = (importlib.import_module(name) for name in names)
    return cache, rollout, generator


def _dictionary_text(stem: str = "organ") -> str:
    """Return a minimal valid shared-dictionary document."""
    return (
        'schema = 1\n\n[oxford]\nstems = ["'
        + stem
        + '"]\n\n[words]\naccepted = []\n\n[words.corrections]\n\n'
        + "[patterns]\nignore = []\n\n[files]\nexclude = []\n"
    )


def test_rollout_generates_oxford_corrections(
    rollout_modules: tuple[types.ModuleType, types.ModuleType, types.ModuleType],
) -> None:
    """The shared renderer accepts Oxford forms and corrects plain-British ones."""
    _, rollout, _ = rollout_modules

    mappings = rollout.generate_word_mappings(rollout.Dictionary(stems=("organ",)))

    assert mappings["organize"] == "organize"
    assert mappings["organise"] == "organize"


def test_local_refresh_keeps_a_newer_cache(
    rollout_modules: tuple[types.ModuleType, types.ModuleType, types.ModuleType],
    tmp_path: Path,
) -> None:
    """An older local authority cannot replace a newer untracked cache."""
    _, rollout, _ = rollout_modules
    source = tmp_path / "shared.toml"
    cache = tmp_path / ".typos-base.toml"
    metadata = tmp_path / ".typos-base.json"
    source.write_text(_dictionary_text(), encoding="utf-8")
    source.touch()
    rollout.refresh_base(source, cache, metadata=metadata)
    cache.write_text(_dictionary_text("newer"), encoding="utf-8")
    cache.touch()
    source_mtime = source.stat().st_mtime_ns
    cache_mtime = max(cache.stat().st_mtime_ns, source_mtime + 1)
    os.utime(cache, ns=(cache_mtime, cache_mtime))

    result = rollout.refresh_base(source, cache, metadata=metadata)

    assert result.status == "current"
    assert rollout.load_dictionary(cache).stems == ("newer",)


def test_https_failure_reuses_valid_tracked_config(
    rollout_modules: tuple[types.ModuleType, types.ModuleType, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A clean network-restricted checkout retains its reviewed policy."""
    _, rollout, generator = rollout_modules
    tracked_config = tmp_path / "typos.toml"
    tracked_config.write_text('[default]\nlocale = "en-gb"\n', encoding="utf-8")

    def unavailable(*_args: object, **_kwargs: object) -> None:
        """Model an unavailable HTTPS authority."""
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(rollout, "refresh_base", unavailable)

    result = generator.main(repository=tmp_path, source="https://example.invalid/base")

    assert result.status == "tracked-config"
    assert result.cache == tracked_config


def test_dictionary_validation_rejects_invalid_documents(
    rollout_modules: tuple[types.ModuleType, types.ModuleType, types.ModuleType],
    tmp_path: Path,
) -> None:
    """Schema, table, string-list and correction types remain validated."""
    _, rollout, _ = rollout_modules
    source = tmp_path / "base.toml"
    invalid_documents = (
        _dictionary_text().replace("schema = 1", "schema = 2"),
        _dictionary_text().replace('[oxford]\nstems = ["organ"]', 'oxford = "bad"'),
        _dictionary_text().replace('stems = ["organ"]', "stems = [1]"),
        _dictionary_text().replace(
            "[words.corrections]", "[words.corrections]\nteh = 1"
        ),
    )

    for document in invalid_documents:
        source.write_text(document, encoding="utf-8")
        with pytest.raises((TypeError, ValueError)):
            rollout.load_dictionary(source)


def test_merge_rejects_conflicting_corrections(
    rollout_modules: tuple[types.ModuleType, types.ModuleType, types.ModuleType],
) -> None:
    """A local overlay cannot silently weaken a shared correction."""
    _, rollout, _ = rollout_modules
    base = rollout.Dictionary(corrections=(("teh", "the"),))
    local = rollout.Dictionary(corrections=(("teh", "ten"),))

    with pytest.raises(ValueError, match="conflicting correction"):
        rollout.merge_dictionaries(base, local)


def test_render_and_write_are_deterministic_valid_toml(
    rollout_modules: tuple[types.ModuleType, types.ModuleType, types.ModuleType],
    tmp_path: Path,
) -> None:
    """Rendering is stable, parseable and atomically installed."""
    _, rollout, _ = rollout_modules
    dictionary = rollout.Dictionary(
        stems=("organ",),
        accepted=("proper-name",),
        ignore_patterns=("https?://",),
        excluded_files=("target",),
    )
    output = tmp_path / "nested" / "typos.toml"

    first = rollout.render_typos_config(dictionary)
    rollout.write_config(output, dictionary)

    assert first == rollout.render_typos_config(dictionary)
    assert output.read_text(encoding="utf-8") == first
    assert tomllib.loads(first)["default"]["locale"] == "en-gb"
    assert list(output.parent.glob(".typos.toml.*")) == []


def test_offline_refresh_requires_and_reuses_valid_cache(
    rollout_modules: tuple[types.ModuleType, types.ModuleType, types.ModuleType],
    tmp_path: Path,
) -> None:
    """Offline mode fails closed before reusing a validated cache."""
    _, rollout, _ = rollout_modules
    cache = tmp_path / "base.toml"
    metadata = tmp_path / "base.json"

    with pytest.raises(FileNotFoundError, match="no cached shared dictionary"):
        rollout.refresh_base(
            "https://example.invalid/base", cache, metadata=metadata, offline=True
        )

    cache.write_text(_dictionary_text(), encoding="utf-8")
    result = rollout.refresh_base(
        "https://example.invalid/base", cache, metadata=metadata, offline=True
    )

    assert result.status == "offline-cache"


def test_local_refresh_switches_authority_and_records_metadata(
    rollout_modules: tuple[types.ModuleType, types.ModuleType, types.ModuleType],
    tmp_path: Path,
) -> None:
    """A different explicit authority replaces a cache regardless of mtime."""
    _, rollout, _ = rollout_modules
    first = tmp_path / "first.toml"
    second = tmp_path / "second.toml"
    cache = tmp_path / "cache.toml"
    metadata = tmp_path / "cache.json"
    first.write_text(_dictionary_text("first"), encoding="utf-8")
    second.write_text(_dictionary_text("second"), encoding="utf-8")
    os.utime(first, ns=(3_000_000_000, 3_000_000_000))
    os.utime(second, ns=(1_000_000_000, 1_000_000_000))
    rollout.refresh_base(first, cache, metadata=metadata)

    result = rollout.refresh_base(second, cache, metadata=metadata)

    assert result.status == "refreshed"
    assert rollout.load_dictionary(cache).stems == ("second",)
    assert json.loads(metadata.read_text(encoding="utf-8"))["source"] == str(
        second.resolve()
    )


def test_http_refresh_uses_validators_and_preserves_newer_cache(
    rollout_modules: tuple[types.ModuleType, types.ModuleType, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Remote refresh persists validators and sends them on the next request."""
    _, rollout, _ = rollout_modules
    cache = tmp_path / "cache.toml"
    metadata = tmp_path / "cache.json"
    requests: list[urllib.request.Request] = []

    class Response:
        """Provide the HTTP response surface consumed by the helper."""

        status = 200
        headers: typ.ClassVar[dict[str, str]] = {
            "ETag": '"estate-v1"',
            "Last-Modified": "Fri, 10 Jul 2026 08:00:00 GMT",
        }

        def read(self) -> bytes:
            """Return a valid shared dictionary."""
            return _dictionary_text().encode()

        def __enter__(self) -> typ.Self:
            """Enter the fake response context."""
            return self

        def __exit__(self, *_args: object) -> None:
            """Leave the fake response context."""

    def open_response(request: urllib.request.Request, *, timeout: float) -> Response:
        """Capture the request passed to the network boundary."""
        assert timeout == pytest.approx(30.0)
        requests.append(request)
        return Response()

    monkeypatch.setattr(rollout.urllib.request, "urlopen", open_response)

    first = rollout.refresh_base(
        "https://example.test/base.toml", cache, metadata=metadata
    )
    second = rollout.refresh_base(
        "https://example.test/base.toml", cache, metadata=metadata
    )

    assert first.status == "refreshed"
    assert second.status == "current"
    assert requests[1].get_header("If-none-match") == '"estate-v1"'


def test_remote_failure_reuses_only_a_valid_stale_cache(
    rollout_modules: tuple[types.ModuleType, types.ModuleType, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Network failure keeps validated data and propagates without it."""
    _, rollout, _ = rollout_modules
    cache = tmp_path / "cache.toml"
    metadata = tmp_path / "cache.json"

    def fail(*_args: object, **_kwargs: object) -> None:
        """Model an unavailable remote authority."""
        message = "offline"
        raise urllib.error.URLError(message)

    monkeypatch.setattr(rollout.urllib.request, "urlopen", fail)

    with pytest.raises(urllib.error.URLError):
        rollout.refresh_base("https://example.test/base", cache, metadata=metadata)

    cache.write_text(_dictionary_text(), encoding="utf-8")
    result = rollout.refresh_base("https://example.test/base", cache, metadata=metadata)

    assert result.status == "stale-cache"


def test_remote_refresh_rejects_insecure_and_invalid_content(
    rollout_modules: tuple[types.ModuleType, types.ModuleType, types.ModuleType],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The remote boundary requires HTTPS and validates bytes before install."""
    _, rollout, _ = rollout_modules
    cache = tmp_path / "cache.toml"
    metadata = tmp_path / "cache.json"

    with pytest.raises(ValueError, match="must use HTTPS"):
        rollout.refresh_base("http://example.test/base", cache, metadata=metadata)

    class InvalidResponse:
        """Return malformed TOML from an otherwise successful response."""

        status = 200
        headers: typ.ClassVar[dict[str, str]] = {}

        def read(self) -> bytes:
            """Return malformed bytes."""
            return b"not = [valid"

        def __enter__(self) -> typ.Self:
            """Enter the fake response context."""
            return self

        def __exit__(self, *_args: object) -> None:
            """Leave the fake response context."""

    monkeypatch.setattr(
        rollout.urllib.request, "urlopen", lambda *_args, **_kwargs: InvalidResponse()
    )

    with pytest.raises(tomllib.TOMLDecodeError):
        rollout.refresh_base("https://example.test/base", cache, metadata=metadata)
    assert not cache.exists()


def test_metadata_reader_handles_invalid_and_non_object_json(
    rollout_modules: tuple[types.ModuleType, types.ModuleType, types.ModuleType],
    tmp_path: Path,
) -> None:
    """Malformed or non-object freshness metadata is safely ignored."""
    _, rollout, _ = rollout_modules
    metadata = tmp_path / "cache.json"

    metadata.write_text("not-json", encoding="utf-8")
    assert rollout._read_metadata(metadata) == {}
    metadata.write_text("[]", encoding="utf-8")
    assert rollout._read_metadata(metadata) == {}


def test_http_error_translation_handles_not_modified_and_stale_cache(
    rollout_modules: tuple[types.ModuleType, types.ModuleType, types.ModuleType],
    tmp_path: Path,
) -> None:
    """HTTP status handling distinguishes current, stale and absent data."""
    _, rollout, _ = rollout_modules
    cache = tmp_path / "cache.toml"
    cache.write_text(_dictionary_text(), encoding="utf-8")
    headers = email.message.Message()
    not_modified = urllib.error.HTTPError(
        "https://example.test/base", 304, "not modified", headers, None
    )
    unavailable = urllib.error.HTTPError(
        "https://example.test/base", 503, "unavailable", headers, None
    )

    assert rollout._http_error_result(cache, not_modified).status == "current"
    assert rollout._http_error_result(cache, unavailable).status == "stale-cache"
    cache.unlink()
    with pytest.raises(urllib.error.HTTPError):
        rollout._http_error_result(cache, unavailable)


def test_remote_freshness_uses_dates_and_falls_back_on_invalid_values(
    rollout_modules: tuple[types.ModuleType, types.ModuleType, types.ModuleType],
) -> None:
    """Last-Modified comparison remains conservative for malformed dates."""
    _, rollout, _ = rollout_modules

    assert rollout._remote_is_not_newer(
        {"last_modified": "Fri, 10 Jul 2026 08:00:00 GMT"},
        {"Last-Modified": "Fri, 10 Jul 2026 07:00:00 GMT"},
    )
    assert rollout._remote_is_not_newer(
        {"last_modified": "invalid"}, {"Last-Modified": "invalid"}
    )
    assert not rollout._remote_is_not_newer({}, {"Last-Modified": "invalid"})


def test_atomic_write_creates_parent_directories_by_default(
    rollout_modules: tuple[types.ModuleType, types.ModuleType, types.ModuleType],
    tmp_path: Path,
) -> None:
    """The default options create missing destination directories."""
    cache, _rollout, _generator = rollout_modules
    destination = tmp_path / "missing" / "nested" / "config.toml"

    cache.atomic_write(destination, b"payload\n")

    assert destination.read_bytes() == b"payload\n", (
        "The destination must hold the replacement content."
    )


def test_atomic_write_without_parent_creation_requires_the_directory(
    rollout_modules: tuple[types.ModuleType, types.ModuleType, types.ModuleType],
    tmp_path: Path,
) -> None:
    """Disabling parent creation surfaces a missing destination directory."""
    cache, _rollout, _generator = rollout_modules
    destination = tmp_path / "missing" / "config.toml"

    with pytest.raises(FileNotFoundError):
        cache.atomic_write(
            destination,
            b"payload\n",
            options=cache.AtomicWriteOptions(create_parents=False),
        )
    assert not destination.exists(), "A failed write must not create the destination."


def test_atomic_write_preserves_an_existing_destination_mode(
    rollout_modules: tuple[types.ModuleType, types.ModuleType, types.ModuleType],
    tmp_path: Path,
) -> None:
    """Mode preservation copies the destination's permissions onto the replacement."""
    cache, _rollout, _generator = rollout_modules
    destination = tmp_path / "config.toml"
    destination.write_bytes(b"old\n")
    destination.chmod(0o640)

    cache.atomic_write(
        destination,
        b"new\n",
        options=cache.AtomicWriteOptions(preserve_mode=True),
    )

    assert destination.read_bytes() == b"new\n", "The content must be replaced."
    assert destination.stat().st_mode & 0o777 == 0o640, (
        "Mode preservation must retain the destination's permission bits."
    )


def test_atomic_write_preserves_mode_only_when_a_destination_exists(
    rollout_modules: tuple[types.ModuleType, types.ModuleType, types.ModuleType],
    tmp_path: Path,
) -> None:
    """Mode preservation must not require an initial destination."""
    cache, _rollout, _generator = rollout_modules
    destination = tmp_path / "new" / "config.toml"

    cache.atomic_write(
        destination,
        b"new\n",
        options=cache.AtomicWriteOptions(preserve_mode=True),
    )

    assert destination.read_bytes() == b"new\n", (
        "A missing destination must still be created when preserving modes."
    )


@dc.dataclass
class _OsSpy:
    """Record what ``atomic_write`` fsyncs, delegating the rest to ``os``.

    ``atomic_write`` closes every descriptor it syncs before it returns, so
    each descriptor is inspected while it is still open and the ``stat`` result
    kept; a later ``os.fstat`` on the recorded number would raise ``EBADF``.
    """

    #: The spy stands in for the whole ``os`` module, so the directory-sync
    #: helper's ``os.O_RDONLY`` has to resolve here too.
    O_RDONLY: typ.ClassVar[int] = os.O_RDONLY

    synced: list[os.stat_result] = dc.field(default_factory=list)

    def fsync(self, descriptor: int) -> None:
        """Record the descriptor's stat, then sync it for real."""
        self.synced.append(os.fstat(descriptor))
        os.fsync(descriptor)

    def open(self, path: Path, flags: int) -> int:
        """Delegate descriptor opening."""
        return os.open(path, flags)

    def close(self, descriptor: int) -> None:
        """Delegate descriptor closing."""
        os.close(descriptor)


@dc.dataclass
class _FailingDirectorySync:
    """Fail the directory sync, recording which descriptors get closed.

    The first ``fsync`` reaches the temporary file and is allowed through; the
    second reaches the directory and raises. ``atomic_write`` opens the
    directory through ``os.open``, so every descriptor recorded here is the
    directory descriptor, and the ``close`` calls show whether that descriptor
    was released on the failing path.
    """

    #: The spy stands in for the whole ``os`` module, so the directory-sync
    #: helper's ``os.O_RDONLY`` has to resolve here too.
    O_RDONLY: typ.ClassVar[int] = os.O_RDONLY

    syncs: int = 0
    opened: list[int] = dc.field(default_factory=list)
    closed: list[int] = dc.field(default_factory=list)

    def fsync(self, descriptor: int) -> None:
        """Sync the temporary file, then fail on the directory."""
        self.syncs += 1
        if self.syncs > 1:
            message = "directory sync failed"
            raise OSError(message)
        os.fsync(descriptor)

    def open(self, path: Path, flags: int) -> int:
        """Delegate descriptor opening, recording the descriptor."""
        descriptor = os.open(path, flags)
        self.opened.append(descriptor)
        return descriptor

    def close(self, descriptor: int) -> None:
        """Delegate descriptor closing, recording the descriptor."""
        self.closed.append(descriptor)
        os.close(descriptor)


def test_atomic_write_closes_the_directory_descriptor_when_the_sync_fails(
    rollout_modules: tuple[types.ModuleType, types.ModuleType, types.ModuleType],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failing directory sync must still release the descriptor it opened."""
    cache, _rollout, _generator = rollout_modules
    destination = tmp_path / "config.toml"
    spy = _FailingDirectorySync()
    monkeypatch.setattr(atomic_write, "os", spy)

    with pytest.raises(OSError, match="directory sync failed"):
        cache.atomic_write(
            destination,
            b"payload\n",
            options=cache.AtomicWriteOptions(sync_file=True),
        )

    assert len(spy.opened) == 1, "The directory descriptor must be opened once."
    assert spy.closed == spy.opened, (
        "The directory descriptor must be closed even when os.fsync raises."
    )
    assert list(tmp_path.glob(f".{destination.name}.*")) == [], (
        "A failed sync must not leave the temporary sibling behind."
    )


def test_atomic_write_syncs_the_temporary_file_when_requested(
    rollout_modules: tuple[types.ModuleType, types.ModuleType, types.ModuleType],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Requesting a sync fsyncs the temporary file and the parent directory."""
    cache, _rollout, _generator = rollout_modules
    destination = tmp_path / "config.toml"
    spy = _OsSpy()
    monkeypatch.setattr(atomic_write, "os", spy)
    cache.atomic_write(
        destination,
        b"payload\n",
        options=cache.AtomicWriteOptions(sync_file=True),
    )

    assert len(spy.synced) == 2, "File and parent directory must each be fsynced."
    regular_files = [s for s in spy.synced if stat.S_ISREG(s.st_mode)]
    directories = [s for s in spy.synced if stat.S_ISDIR(s.st_mode)]
    assert len(regular_files) == 1, "Exactly one fsync must target the temporary file."
    assert len(directories) == 1, "Exactly one fsync must target the parent directory."
    assert destination.read_bytes() == b"payload\n", "The write must still complete."
