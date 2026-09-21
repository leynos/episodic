"""Regression tests for logging-port call-site enforcement."""

import pathlib as pl
import re
import shutil
import subprocess  # noqa: S404  # The test invokes a fixed local typechecker command.

REPOSITORY_ROOT = pl.Path(__file__).resolve().parents[1]
DIRECT_CALL_FIXTURE = (
    REPOSITORY_ROOT
    / "tests"
    / "fixtures"
    / "typecheck"
    / "logging_handle_direct_call.py"
)
DIRECT_LOGGER_CALL_PATTERN = re.compile(
    r"\b(?:logger|_log|_logger|effective_log)\.(?:debug|info|warning|error|critical|log)\("
)


def test_typechecker_rejects_direct_logger_handle_calls() -> None:
    """The opaque handle rejects raw level-method calls under ty."""
    uv_executable = shutil.which("uv")
    assert uv_executable is not None, "Expected uv to run the pinned ty release."
    completed_process = subprocess.run(  # noqa: S603  # Static local command and fixture path.
        [
            uv_executable,
            "tool",
            "run",
            "ty==0.0.32",
            "check",
            str(DIRECT_CALL_FIXTURE),
        ],
        check=False,
        capture_output=True,
        cwd=REPOSITORY_ROOT,
        text=True,
        timeout=30,
    )

    rendered = f"{completed_process.stdout}\n{completed_process.stderr}"
    assert completed_process.returncode != 0, rendered
    assert "info" in rendered, rendered
    assert "LoggerHandle" in rendered, rendered


def test_production_logger_calls_use_the_logging_port() -> None:
    """Production modules must not call logger level methods directly."""
    offending_paths = {
        path.relative_to(REPOSITORY_ROOT).as_posix()
        for path in (REPOSITORY_ROOT / "episodic").glob("**/*.py")
        if path != REPOSITORY_ROOT / "episodic" / "logging.py"
        and DIRECT_LOGGER_CALL_PATTERN.search(path.read_text(encoding="utf-8"))
    }

    assert not offending_paths, (
        f"Logger level methods bypass the logging port in: {sorted(offending_paths)!r}"
    )
