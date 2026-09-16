"""Contract tests keeping Makefile and CI toolchain pins in sync.

The Makefile pins the ``nose`` duplication detector installed for the
``lint`` gate, and the CI workflow installs the same binary through
``cargo binstall``. These tests assert that both places pin the same
version without asserting any specific version: bumping a pin is a routine
change, but letting the two definitions drift silently produces a gate that
passes locally and fails in CI (or the reverse).
"""

import re
import typing as typ
from pathlib import Path

import pytest

if typ.TYPE_CHECKING:
    from syrupy.assertion import SnapshotAssertion

_REPO_ROOT = Path(__file__).resolve().parents[1]
MAKEFILE_PATH = _REPO_ROOT / "Makefile"
CI_WORKFLOW_PATH = _REPO_ROOT / ".github" / "workflows" / "ci.yml"
PYPROJECT_PATH = _REPO_ROOT / "pyproject.toml"
NOSE_TOOL = "nose"

pytestmark = pytest.mark.skipif(
    not (
        MAKEFILE_PATH.exists() and CI_WORKFLOW_PATH.exists() and PYPROJECT_PATH.exists()
    ),
    reason=(
        "Makefile, pyproject.toml, or CI workflow not present in this working "
        "copy (for example inside a mutation-testing sandbox that does not "
        "copy the repository root or .github/)"
    ),
)

#: PEP 440-flavoured shape check so an accidentally emptied pin fails
#: loudly rather than comparing two empty strings as equal.
VERSION_RE = re.compile(r"\d+(?:\.\d+)+(?:[a-zA-Z0-9.+-]*)")


def _makefile_pin() -> str:
    """Extract the nose pinned version from the Makefile.

    Returns
    -------
    str
        The version string assigned to ``NOSE_VERSION``.
    """
    variable = f"{NOSE_TOOL.upper()}_VERSION"
    text = MAKEFILE_PATH.read_text(encoding="utf-8")
    match = re.search(
        rf"^{re.escape(variable)}\s*\??=\s*(\S+)\s*$", text, flags=re.MULTILINE
    )
    assert match is not None, f"{variable} is not defined in the Makefile"
    return match.group(1)


def _ci_pin() -> str:
    """Extract the nose pinned version from the CI workflow.

    Returns
    -------
    str
        The version string pinned in ci.yml as ``NOSE_VERSION``.
    """
    variable = f"{NOSE_TOOL.upper()}_VERSION"
    text = CI_WORKFLOW_PATH.read_text(encoding="utf-8")
    matches = re.findall(
        rf'^\s*{re.escape(variable)}:\s*"([^"]*)"\s*$', text, flags=re.MULTILINE
    )
    assert matches, f'ci.yml does not pin {NOSE_TOOL} via {variable}: "..."'
    assert len(matches) == 1, f"ci.yml pins {NOSE_TOOL} more than once: {matches}"
    return matches[0]


def _ci_nose_installation_step() -> str:
    """Return CI's complete nose-detector installation step."""
    text = CI_WORKFLOW_PATH.read_text(encoding="utf-8")
    start = text.index("      - name: Install nose duplication detector")
    end = text.index("      - name: Install CLI tools", start)
    step = text[start:end].rstrip()
    return (
        re
        .sub(
            r'(?<=BINSTALL_SHA256: ")[0-9a-f]{64}(?=")',
            "<sha256>",
            step,
        )
        .replace(
            "https://github.com/cargo-bins/cargo-binstall/releases/download/"
            "${BINSTALL_VERSION}/cargo-binstall-x86_64-unknown-linux-musl.tgz",
            "<cargo-binstall release>",
        )
        .replace("https://github.com/corca-ai/nose", "<nose repository>")
    )


def _gate_pin() -> str:
    """Return the detector version the duplication gate verifies at runtime."""
    text = PYPROJECT_PATH.read_text(encoding="utf-8")
    match = re.search(
        r"^\[tool\.nose\]$.*?^version\s*=\s*\"([^\"]*)\"",
        text,
        flags=re.MULTILINE | re.DOTALL,
    )
    assert match is not None, "pyproject.toml does not set [tool.nose] version"
    return match.group(1)


class TestToolchainPins:
    """The coordinated pins for the nose duplication detector."""

    def test_makefile_and_ci_pin_the_same_version(self) -> None:
        """The Makefile and ci.yml must pin nose to the same version."""
        makefile_version = _makefile_pin()
        ci_version = _ci_pin()
        assert VERSION_RE.fullmatch(makefile_version), (
            f"Makefile {NOSE_TOOL.upper()}_VERSION does not look like a version: "
            f"{makefile_version!r}"
        )
        assert makefile_version == ci_version, (
            f"{NOSE_TOOL} version drift: Makefile pins {makefile_version} but "
            f"ci.yml installs {ci_version}"
        )

    def test_gate_verifies_the_pinned_detector_version(self) -> None:
        """The gate's ``[tool.nose]`` pin must match the installed version."""
        makefile_version = _makefile_pin()
        gate_version = _gate_pin()
        assert VERSION_RE.fullmatch(gate_version), (
            f"[tool.nose] version does not look like a version: {gate_version!r}"
        )
        assert makefile_version == gate_version, (
            f"{NOSE_TOOL} version drift: Makefile pins {makefile_version} but the "
            f"gate verifies {gate_version}"
        )

    @pytest.mark.parametrize(
        "usage_re",
        [
            r"'nose-cli@\$\(NOSE_VERSION\)'",
            r'"nose \$\(NOSE_VERSION\)"',
        ],
        ids=["binstall-install", "version-check"],
    )
    def test_makefile_commands_use_the_pinned_version(self, usage_re: str) -> None:
        """The Makefile's tool invocations must reference the version variable."""
        text = MAKEFILE_PATH.read_text(encoding="utf-8")
        assert re.search(usage_re, text), (
            f"the Makefile defines {NOSE_TOOL.upper()}_VERSION but its "
            f"{NOSE_TOOL} command does not reference it (expected pattern {usage_re})"
        )

    def test_ci_installs_the_pinned_detector_with_binstall(
        self,
        snapshot: SnapshotAssertion,
    ) -> None:
        """CI must install nose through the pinned cargo-binstall command."""
        assert _ci_nose_installation_step() == snapshot, (
            "CI's nose-detector installation contract must match its snapshot."
        )


def _workflow_text() -> str:
    """Return the CI workflow source."""
    return CI_WORKFLOW_PATH.read_text(encoding="utf-8")


def _cache_step(name: str) -> str:
    """Return one ``actions/cache`` step, from its ``- name:`` to the next step.

    Returns
    -------
    str
        The YAML block for the named cache step, without trailing blank lines.
    """
    text = _workflow_text()
    start = text.index(f"      - name: {name}")
    end = text.find("\n      - name:", start + 1)
    return text[start:] if end == -1 else text[start:end].rstrip()


def _cache_key(step: str) -> str:
    """Extract the ``key:`` expression from a cache step."""
    match = re.search(r"^\s*key:\s*(.+?)\s*$", step, flags=re.MULTILINE)
    assert match is not None, f"cache step declares no key:\n{step}"
    return match.group(1)


def _block_entries(step: str, field: str) -> tuple[str, ...]:
    """Read one indented block scalar (``field: |``) as a list of entries.

    Entries are compared exactly rather than by substring, so a mistyped path
    that merely contains a correct-looking prefix cannot satisfy a check.

    Returns
    -------
    tuple[str, ...]
        The block's entries, in order.

    Raises
    ------
    AssertionError
        If the step declares no such block scalar.

    """
    lines = step.splitlines()
    for index, line in enumerate(lines):
        if line.strip() != f"{field}: |":
            continue
        indent = len(line) - len(line.lstrip())
        entries: list[str] = []
        for following in lines[index + 1 :]:
            if not following.strip():
                continue
            if len(following) - len(following.lstrip()) <= indent:
                break
            entries.append(following.strip())
        return tuple(entries)
    msg = f"cache step declares no {field}: block:\n{step}"
    raise AssertionError(msg)


def _restore_keys(step: str) -> tuple[str, ...]:
    """Extract the ``restore-keys:`` block entries from a cache step.

    The block scalar is read by indentation rather than by pattern, because a
    restore key may itself contain spaces (as ``${{ runner.os }}`` does).

    Returns
    -------
    tuple[str, ...]
        The restore-key prefixes, in order.

    Raises
    ------
    AssertionError
        If the step declares no ``restore-keys`` block.

    """
    lines = step.splitlines()
    for index, line in enumerate(lines):
        if line.strip() != "restore-keys: |":
            continue
        indent = len(line) - len(line.lstrip())
        keys: list[str] = []
        for following in lines[index + 1 :]:
            if not following.strip():
                continue
            if len(following) - len(following.lstrip()) <= indent:
                break
            keys.append(following.strip())
        return tuple(keys)
    msg = f"cache step declares no restore-keys:\n{step}"
    raise AssertionError(msg)


class TestCiCacheContract:
    """The CI cache blocks that keep tool environments between runs.

    A cache that silently stops being populated, or that is keyed on the
    wrong inputs, is invisible until a run re-installs everything or, worse,
    restores a tool environment a pin change should have invalidated. These
    tests pin the paths and invalidation keys the workflow depends on.
    """

    def test_uv_cache_covers_the_repo_local_tool_directories(self) -> None:
        """The uv cache must carry the repo-local cache and tool trees."""
        paths = _block_entries(
            _cache_step("Cache uv tool and script environments"), "path"
        )
        assert set(paths) == {".uv-cache", ".uv-tools"}, (
            "the uv cache must cover exactly the repo-local directories the "
            f"Makefile scopes uv to; got {paths!r}"
        )

    def test_uv_cache_key_hashes_every_pin_the_environment_depends_on(self) -> None:
        """The uv cache key must invalidate when a tool pin moves."""
        key = _cache_key(_cache_step("Cache uv tool and script environments"))
        assert "hashFiles(" in key, f"the uv cache key must hash inputs, got {key!r}"
        for hashed in ("uv.lock", "Makefile", "scripts/*.py"):
            assert hashed in key, (
                f"the uv cache key must hash {hashed!r}, which pins tool "
                f"versions the cached environments depend on; got {key!r}"
            )

    def test_uv_cache_restores_to_the_same_runner_os(self) -> None:
        """A restore-key prefix must not cross operating systems."""
        step = _cache_step("Cache uv tool and script environments")
        keys = _restore_keys(step)
        assert any("${{ runner.os }}" in key for key in keys), (
            "the uv cache restore key must be scoped to runner.os so a cache "
            f"from another platform cannot be restored; got {keys!r}"
        )

    def test_nose_cache_covers_the_detector_install_directory(self) -> None:
        """The detector cache must carry the directory the recipe installs into."""
        step = _cache_step("Cache the pinned nose duplication detector")
        match = re.search(r"^\s*path:\s*(\S+)\s*$", step, flags=re.MULTILINE)
        assert match is not None, f"the detector cache declares no path:\n{step}"
        assert match.group(1) == ".tools/nose", (
            "the detector cache must carry the install directory itself, not "
            f"a larger or mistyped path; got {match.group(1)!r}"
        )

    def test_nose_cache_key_carries_the_pinned_version(self) -> None:
        """A version bump must miss the detector cache and reinstall."""
        key = _cache_key(_cache_step("Cache the pinned nose duplication detector"))
        assert "NOSE_VERSION" in key, (
            "the detector cache key must carry the pinned version so bumping "
            f"the pin forces a reinstall; got {key!r}"
        )

    def test_detector_cache_directory_matches_the_install_target(self) -> None:
        """The cached directory must be the one the recipe writes the binary to."""
        makefile = MAKEFILE_PATH.read_text(encoding="utf-8")
        match = re.search(
            r"^NOSE_TOOLS_DIR\s*\??=\s*(\S+)\s*$", makefile, flags=re.MULTILINE
        )
        assert match is not None, "NOSE_TOOLS_DIR is not defined in the Makefile"
        cached = re.search(
            r"^\s*path:\s*(\S+)\s*$",
            _cache_step("Cache the pinned nose duplication detector"),
            flags=re.MULTILINE,
        )
        assert cached is not None, "the detector cache step declares no path"
        assert cached.group(1) == match.group(1), (
            f"CI caches {cached.group(1)!r} but the Makefile installs nose into "
            f"{match.group(1)!r}; a cache of the wrong directory never hits"
        )
        assert f"mkdir -p {match.group(1)}" in _workflow_text(), (
            "CI must create the detector install directory before binstall runs"
        )
