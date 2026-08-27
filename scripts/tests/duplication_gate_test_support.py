"""Shared subprocess support for duplication-gate workflow tests."""

import json
import os
import shutil
import subprocess  # noqa: S404 - support invokes fixed test commands.
import sys
from pathlib import Path

import duplication_allowlist as allowlist
import duplication_gate as gate
import nose_detector as detector
import nose_schema as schema

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

#: Report emitted by the stub detector: one two-member duplication family.
STUB_REPORT: dict[str, object] = {
    "schema_version": 9,
    "families": [
        {
            "id": "stub",
            "witness": "copy-paste",
            "surface": "default",
            "value": 22.1,
            "metrics": {"mean_score": 1.0},
            "locations": [
                {"file": "episodic/a.py", "start": 1, "end": 20, "name": None},
                {"file": "episodic/b.py", "start": 30, "end": 49, "name": None},
            ],
        }
    ],
}


def copied_gate_workspace(tmp_path: Path) -> tuple[Path, Path]:
    """Create a mutable workspace containing the gate and its helper modules."""
    workspace = tmp_path / "gate-workspace"
    scripts = workspace / "scripts"
    scripts.mkdir(parents=True)
    for name in (
        "duplication_allowlist.py",
        "duplication_gate.py",
        "nose_detector.py",
        "nose_schema.py",
        "typos_rollout_cache.py",
    ):
        shutil.copy(REPOSITORY_ROOT / "scripts" / name, scripts / name)
    (workspace / "pyproject.toml").write_text(
        '[project]\nname = "gate-test"\nversion = "0"\n', encoding="utf-8"
    )
    return workspace, scripts / "duplication_gate.py"


def write_stub_nose(
    directory: Path,
    *,
    version: str = "nose 0.20.0",
    report: dict[str, object] | None = None,
) -> Path:
    """Write an executable stub standing in for the pinned nose binary.

    The stub answers ``--version`` and otherwise prints one canned JSON
    report, so gate tests exercise the real subprocess boundary without
    depending on a downloaded detector.

    Returns
    -------
    pathlib.Path
        Path to the executable stub.
    """
    stub = directory / "nose"
    payload = STUB_REPORT if report is None else report
    stub.write_text(
        f"#!{sys.executable}\n"
        "import json, sys\n"
        "if '--version' in sys.argv:\n"
        f"    print({version!r})\n"
        "    raise SystemExit(0)\n"
        f"print(json.dumps({payload!r}))\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)
    return stub


def gate_command(script: Path, *arguments: str) -> list[str]:
    """Build an isolated Python command for a copied gate script."""
    return [sys.executable, str(script), *arguments]


def gate_environment(**overrides: str) -> dict[str, str]:
    """Build a deterministic environment for gate subprocesses."""
    return {**os.environ, **overrides}


def run_gate_command(
    script: Path,
    *arguments: str,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a copied gate command and capture its completed result."""
    return subprocess.run(  # noqa: S603 - fixed test interpreter and copied script.
        gate_command(script, *arguments),
        cwd=script.parent.parent,
        env=gate_environment() if environment is None else environment,
        check=False,
        capture_output=True,
        text=True,
    )


def stub_settings(  # noqa: PLR0913 - mirrors every NoseSettings field.
    *,
    version: str = "0.20.0",
    roots: tuple[str, ...] = ("episodic",),
    mode: str = "syntax,semantic,near",
    min_size: int = 24,
    surface: str = "all",
    top: int | None = 30,
    exclude: tuple[str, ...] = (),
) -> detector.NoseSettings:
    """Build detector settings for tests, overriding selected fields."""
    return detector.NoseSettings(
        version=version,
        roots=roots,
        mode=mode,
        min_size=min_size,
        surface=surface,
        top=top,
        exclude=exclude,
    )


def stub_runner(*, version: str = "nose 0.20.0", report: object = None):  # noqa: ANN201 - returns a closure over test doubles.
    """Build a command runner double answering version and query commands."""
    payload = STUB_REPORT if report is None else report

    def run(command: list[str] | tuple[str, ...]) -> str:
        if "--version" in command:
            return f"{version}\n"
        return json.dumps(payload)

    return run


__all__ = [
    "REPOSITORY_ROOT",
    "STUB_REPORT",
    "allowlist",
    "copied_gate_workspace",
    "detector",
    "gate",
    "gate_command",
    "gate_environment",
    "run_gate_command",
    "schema",
    "stub_runner",
    "stub_settings",
    "write_stub_nose",
]
