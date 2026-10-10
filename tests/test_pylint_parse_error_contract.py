"""End-to-end contract for Pylint's syntax-error reporting."""

import shlex
import shutil
import subprocess  # ruff: ignore[suspicious-subprocess-import]  # Drives Make's Pylint recipe.
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PROBE_TARGET: str = "jm5-pylint-probe"


def _make_quoted(path: Path) -> str:
    """Quote a path for a shell word inside a Make recipe.

    Parameters
    ----------
    path : Path
        The path to quote.

    Returns
    -------
    str
        The shell-quoted path with each ``$`` doubled, so Make passes it to
        the shell as one literal word.
    """
    return shlex.quote(str(path)).replace("$", "$$")


def _run_configured_pylint(target: Path) -> subprocess.CompletedProcess[str]:
    """Run the Makefile's own `$(PYLINT)` command over one module.

    Parameters
    ----------
    target : Path
        The module to lint.

    Returns
    -------
    subprocess.CompletedProcess[str]
        The finished Make process, with output captured.
    """
    make = shutil.which("make")
    assert make is not None, "make must be on PATH"
    return subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]  # Fixed argv; the target is a test file.
        [
            make,
            "--no-print-directory",
            "-s",
            "-C",
            str(_REPO_ROOT),
            "--eval",
            f"{_PROBE_TARGET}: ; $(PYLINT) {_make_quoted(target)}",
            _PROBE_TARGET,
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=600,
    )


@pytest.mark.skipif(
    shutil.which("uv") is None or shutil.which("make") is None,
    reason="the end-to-end check needs make and uv",
)
@pytest.mark.timeout(620)
def test_configured_pylint_fails_on_an_unparseable_module(tmp_path: Path) -> None:
    """The configured tier must fail on a parse error and pass a clean module.

    This drives the real `$(PYLINT)` command, so it catches a disabled
    `syntax-error` wherever it is configured, not only in the file the
    contract above reads.
    """
    broken = tmp_path / "broken_module.py"
    broken.write_text("def broken(\n    return 1\n", encoding="utf-8")
    clean = tmp_path / "clean_module.py"
    clean.write_text('"""A clean module."""\n\nVALUE = 1\n', encoding="utf-8")

    failed = _run_configured_pylint(broken)
    passed = _run_configured_pylint(clean)

    assert failed.returncode != 0, (
        f"a module Pylint cannot parse must fail the tier: {failed.stdout}"
    )
    assert "syntax-error" in failed.stdout, (
        f"the failure must be the parse error: {failed.stdout}{failed.stderr}"
    )
    assert passed.returncode == 0, (
        f"a clean module must pass the tier: {passed.stdout}{passed.stderr}"
    )
