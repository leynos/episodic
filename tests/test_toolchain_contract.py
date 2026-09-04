"""Contract tests keeping Makefile and CI toolchain pins in sync.

The Makefile pins the ``nose`` duplication detector installed for the
``lint`` gate, and the CI workflow installs the same binary through
``cargo binstall``. These tests assert that both places pin the same
version without asserting any specific version: bumping a pin is a routine
change, but letting the two definitions drift silently produces a gate that
passes locally and fails in CI (or the reverse).
"""

import re
from pathlib import Path

import pytest

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
        "Makefile or CI workflow not present in this working copy (for "
        "example inside a mutation-testing sandbox that does not copy the "
        "repository root or .github/)"
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

    def test_ci_installs_the_pinned_detector_with_binstall(self) -> None:
        """CI must install nose through the pinned cargo-binstall command."""
        text = CI_WORKFLOW_PATH.read_text(encoding="utf-8")
        assert 'cargo-binstall" --no-confirm --install-path .tools/nose' in text, (
            "ci.yml must install nose with cargo binstall into .tools/nose"
        )
        assert '"nose-cli@${NOSE_VERSION}"' in text, (
            "ci.yml's nose install must reference the NOSE_VERSION pin"
        )
        assert "BINSTALL_VERSION" in text, "ci.yml must pin the cargo-binstall release."
        assert "BINSTALL_SHA256" in text, (
            "ci.yml must verify the cargo-binstall release."
        )
