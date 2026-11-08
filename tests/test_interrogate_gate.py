"""Behaviour tests for the ``make interrogate`` docstring-coverage gate.

The tests replace the Interrogate command with a stub script, so they check
what the target does with a report and an exit status rather than the wording
of the recipe. A gap hidden by a rounded percentage, a tool that fails, and a
clean report each have their own case, and a dry run of ``make lint`` shows the
gate is a prerequisite of the lint target.
"""

import shutil
import stat
import subprocess  # ruff: ignore[suspicious-subprocess-import] - the tests run make against a stub command.
import typing as typ
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
MAKE = shutil.which("make")

pytestmark = pytest.mark.skipif(MAKE is None, reason="make is not installed")

CLEAN_REPORT = (
    "| episodic/app.py | COVERED |\nRESULT: PASSED (minimum: 100.0%, actual: 100.0%)\n"
)
MISSED_REPORT = (
    "| episodic/app.py |  MISSED |\nRESULT: PASSED (minimum: 100.0%, actual: 100.0%)\n"
)


def write_stub(directory: Path, report: str, exit_code: int) -> Path:
    """Write an executable stand-in that prints ``report`` and exits ``exit_code``."""
    report_file = directory / "report.txt"
    report_file.write_text(report, encoding="utf-8")
    script = directory / "interrogate-stub"
    script.write_text(
        f'#!/bin/sh\ncat "{report_file}"\nexit {exit_code}\n', encoding="utf-8"
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return script


def run_make(*arguments: str) -> subprocess.CompletedProcess[str]:
    """Run make in the repository root with ``arguments`` and capture its output."""
    command: list[str] = [typ.cast("str", MAKE), "-C", str(REPOSITORY_ROOT), *arguments]
    return subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] - fixed arguments, no shell.
        command,
        capture_output=True,
        text=True,
        check=False,
    )


def test_clean_report_passes(tmp_path: Path) -> None:
    """A fully documented report with a zero exit status passes the gate."""
    stub = write_stub(tmp_path, CLEAN_REPORT, 0)

    result = run_make("-s", "interrogate", f"INTERROGATE={stub}")

    assert result.returncode == 0, result.stderr


def test_missed_row_fails_despite_successful_exit(tmp_path: Path) -> None:
    """A MISSED row fails the gate even when the tool itself exits zero."""
    stub = write_stub(tmp_path, MISSED_REPORT, 0)

    result = run_make("-s", "interrogate", f"INTERROGATE={stub}")

    assert result.returncode != 0, "a MISSED row must fail the gate"
    assert "undocumented definitions remain" in result.stderr, result.stderr


def test_tool_failure_status_propagates(tmp_path: Path) -> None:
    """A non-zero tool exit fails the gate and make reports that status."""
    stub = write_stub(tmp_path, CLEAN_REPORT, 3)

    result = run_make("-s", "interrogate", f"INTERROGATE={stub}")

    assert result.returncode != 0, "a failing tool must fail the gate"
    assert "Error 3" in result.stderr, result.stderr


def test_lint_runs_the_gate() -> None:
    """A dry run of ``make lint`` reaches the interrogate recipe."""
    marker = "interrogate-gate-marker"

    result = run_make("-n", "lint", f"INTERROGATE={marker}")

    assert result.returncode == 0, result.stderr
    assert marker in result.stdout, "lint must reach the interrogate recipe"
    position = result.stdout.index(marker)
    for other_prerequisite in ("hecate", "nose"):
        assert position < result.stdout.index(other_prerequisite), (
            f"the docstring gate must run before the {other_prerequisite} step"
        )
