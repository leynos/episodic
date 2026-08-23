"""Shared subprocess support for duplication-gate workflow tests."""

import os
import shutil
import subprocess  # noqa: S404 - support invokes fixed test commands.
import sys
from pathlib import Path

import pytest

try:
    import duplication_gate as _gate
except ImportError:  # pragma: no cover - Python 3.14 path
    pytest.skip(
        "duplication_gate requires PyChase, which needs Python < 3.14",
        allow_module_level=True,
    )
except AttributeError as error:  # pragma: no cover - Python 3.14 path
    if str(error) != "module 'ast' has no attribute 'Str'":
        raise
    pytest.skip(
        "duplication_gate requires PyChase, which needs Python < 3.14",
        allow_module_level=True,
    )

gate = _gate

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def copied_gate_workspace(tmp_path: Path) -> tuple[Path, Path]:
    """Create a mutable workspace containing the gate and its shared writer."""
    workspace = tmp_path / "gate-workspace"
    scripts = workspace / "scripts"
    scripts.mkdir(parents=True)
    for name in ("duplication_gate.py", "typos_rollout_cache.py"):
        shutil.copy(REPOSITORY_ROOT / "scripts" / name, scripts / name)
    (workspace / "pyproject.toml").write_text(
        '[project]\nname = "gate-test"\nversion = "0"\n', encoding="utf-8"
    )
    return workspace, scripts / "duplication_gate.py"


def gate_command(script: Path, *arguments: str) -> list[str]:
    """Build an isolated Python command for a copied gate script."""
    return [sys.executable, str(script), *arguments]


def gate_environment() -> dict[str, str]:
    """Build a deterministic environment for gate subprocesses."""
    return {**os.environ, "PYTHONHASHSEED": "0"}


def run_gate_command(
    script: Path,
    *arguments: str,
) -> subprocess.CompletedProcess[str]:
    """Run a copied gate command and capture its completed result."""
    return subprocess.run(  # noqa: S603 - fixed test interpreter and copied script.
        gate_command(script, *arguments),
        cwd=script.parent.parent,
        env=gate_environment(),
        check=False,
        capture_output=True,
        text=True,
    )
