"""Contract tests for the Pylint lint tier.

The tier runs a pinned Pylint as a uv tool on managed CPython 3.14. Two
properties of that tier are easy to lose without any test noticing: the
interpreter pin, which decides the grammar Pylint parses with, and the
`syntax-error` message, which decides whether a module that grammar cannot
parse fails the lint or is skipped without a word. Both regressed silently
before: a bare `pypy` moved to a newer PyPy with no commit here, and a
disabled `syntax-error` let unparseable modules go unlinted.
"""

import dataclasses as dc
import os
import re
import shlex
import shutil
import subprocess  # ruff: ignore[suspicious-subprocess-import]  # The end-to-end test drives Make.
import tempfile
import tomllib
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
MAKEFILE_PATH = _REPO_ROOT / "Makefile"
CONFIG_PATH = _REPO_ROOT / "pyproject.toml"

_JOBS_PROBE_TARGET: str = "jm5-pylint-jobs-probe"
_JOBS_PROBE_VARIABLES = (
    "PYLINT_JOBS",
    "DF12_PYLINT_BASE",
    "PYLINT",
    "DF12_PYLINT",
    "DF12_FUTURE_ANNOTATIONS",
)


@dc.dataclass(frozen=True, slots=True)
class _JobsProbeSettings:
    """Inputs that control one isolated Make variable probe."""

    nproc_result: str | None
    nproc_exit_code: int = 0
    environment_jobs: str | None = None
    command_line_jobs: str | None = None


def _makefile_variable(name: str) -> str:
    """Return the value assigned to a Makefile variable.

    Parameters
    ----------
    name : str
        The variable name, assigned with ``=`` or ``?=``.

    Returns
    -------
    str
        The assigned value with surrounding whitespace removed.
    """
    # Join backslash continuations so a multi-line assignment reads whole.
    text = MAKEFILE_PATH.read_text(encoding="utf-8").replace("\\\n", " ")
    match = re.search(rf"^{re.escape(name)}\s*\??=\s*(.+)$", text, flags=re.MULTILINE)
    assert match is not None, f"{name} is not defined in the Makefile"
    return match.group(1).strip()


def test_pylint_tier_pins_the_interpreter() -> None:
    """The tier must name the interpreter whose grammar it parses with."""
    assert _makefile_variable("PYLINT_PYTHON") == "3.14", (
        "PYLINT_PYTHON must stay 3.14: the source uses 3.14 syntax"
    )


def test_pylint_tier_runs_the_pinned_release_on_managed_python() -> None:
    """The tier must run the pinned Pylint on a uv-managed interpreter."""
    assert _makefile_variable("PYLINT_VERSION") == "4.0.9", (
        "PYLINT_VERSION must pin the reviewed Pylint release exactly"
    )
    command = _makefile_variable("PYLINT")
    for fragment in (
        "tool run --managed-python --python $(PYLINT_PYTHON)",
        "--from 'pylint==$(PYLINT_VERSION)' pylint",
    ):
        assert fragment in command, f"PYLINT must contain {fragment!r}: {command}"


def _make_jobs_probe_source() -> str:
    """Print the expanded Make assignments without running their commands."""
    assignments: list[str] = [
        f"$(info __MAKE_PROBE_{name}__=$({name}))" for name in _JOBS_PROBE_VARIABLES
    ]
    assignments.extend([
        f".PHONY: {_JOBS_PROBE_TARGET}",
        f"{_JOBS_PROBE_TARGET}: ; @:",
    ])
    return "\n".join(assignments)


def _parse_jobs_probe_output(stdout: str) -> dict[str, str]:
    """Collect each expanded Make variable exactly once."""
    values: dict[str, str] = {}
    for name in _JOBS_PROBE_VARIABLES:
        prefix = f"__MAKE_PROBE_{name}__="
        matching_lines = [
            line.removeprefix(prefix)
            for line in stdout.splitlines()
            if line.startswith(prefix)
        ]
        assert len(matching_lines) == 1, (
            f"the Make probe must report {name} exactly once: {stdout}"
        )
        values[name] = matching_lines[0]
    return values


def _write_controlled_nproc(
    home: Path,
    *,
    result: str,
    exit_code: int,
    marker: Path,
) -> None:
    """Install an isolated `nproc` executable under Make's first PATH entry."""
    executable_dir = home / ".local" / "bin"
    executable_dir.mkdir(parents=True, exist_ok=True)
    executable = executable_dir / "nproc"
    lines = [
        "#!/bin/sh",
        f"printf '%s\\n' called >> {shlex.quote(str(marker))}",
    ]
    if result:
        lines.append(f"printf '%s\\n' {shlex.quote(result)}")
    lines.append(f"exit {exit_code}")
    executable.write_text("\n".join(lines) + "\n", encoding="utf-8")
    executable.chmod(0o755)


def _pylint_jobs_probe_environment(
    tmp_path: Path,
    home: Path,
    settings: _JobsProbeSettings,
) -> tuple[dict[str, str], Path]:
    """Create an isolated Make environment with a controlled core probe."""
    (home / ".local" / "bin").mkdir(parents=True)
    (home / ".bun" / "bin").mkdir(parents=True)
    marker = tmp_path / "nproc-called"
    if settings.nproc_result is not None:
        _write_controlled_nproc(
            home,
            result=settings.nproc_result,
            exit_code=settings.nproc_exit_code,
            marker=marker,
        )

    # Make itself prepends this isolated HOME's bin directories to PATH.
    path = (
        str(tmp_path / "path-without-nproc")
        if settings.nproc_result is None
        else os.defpath
    )
    environment = {
        "HOME": str(home),
        "PATH": path,
        "LANG": "C",
        "LC_ALL": "C",
    }
    if settings.environment_jobs is not None:
        environment["PYLINT_JOBS"] = settings.environment_jobs
    return environment, marker


def _run_pylint_jobs_probe(
    tmp_path: Path,
    settings: _JobsProbeSettings,
) -> dict[str, str]:
    """Expand the Makefile's Pylint commands in a controlled subprocess."""
    make = shutil.which("make")
    assert make is not None, "make must be on PATH"

    # The test does not inherit Make variables, flags, or the user's HOME.
    # pytest's temporary directory may be on a noexec mount in CI. Make runs
    # `nproc` directly, so keep the controlled executable on the checkout's
    # filesystem while all probe data remains under pytest's temporary path.
    with tempfile.TemporaryDirectory(
        prefix=".pylint-jobs-home-", dir=_REPO_ROOT
    ) as home_name:
        make_environment, marker = _pylint_jobs_probe_environment(
            tmp_path,
            Path(home_name),
            settings,
        )

        probe_makefile = tmp_path / "pylint-jobs-probe.mk"
        probe_makefile.write_text(
            f"include {MAKEFILE_PATH}\n{_make_jobs_probe_source()}\n",
            encoding="utf-8",
        )
        arguments = [
            make,
            "--no-print-directory",
            "-s",
            "-C",
            str(_REPO_ROOT),
            "-f",
            str(probe_makefile),
        ]
        if settings.command_line_jobs is not None:
            arguments.append(f"PYLINT_JOBS={settings.command_line_jobs}")
        arguments.append(_JOBS_PROBE_TARGET)

        completed = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]  # Fixed Make argv; no lint recipe runs.
            arguments,
            capture_output=True,
            text=True,
            check=False,
            env=make_environment,
            timeout=10,
        )
        assert completed.returncode == 0, (
            "the Makefile variable probe must complete without running lint tools: "
            f"{completed.stdout}{completed.stderr}"
        )
        has_override = (
            settings.environment_jobs is not None
            or settings.command_line_jobs is not None
        )
        if settings.nproc_result is not None and not has_override:
            controlled_nproc = Path(make_environment["HOME"]) / ".local/bin/nproc"
            assert marker.is_file(), (
                "Make's PATH prefixes must select the controlled executable "
                f"{controlled_nproc}; PATH={make_environment['PATH']!r}."
            )

        return _parse_jobs_probe_output(completed.stdout)


def _assert_expanded_pylint_jobs(
    values: dict[str, str],
    expected_jobs: int,
) -> None:
    """Check one worker option per command and inheritance from the DF12 base."""
    base = shlex.split(values["DF12_PYLINT_BASE"])
    commands = {
        name: shlex.split(values[name])
        for name in ("PYLINT", "DF12_PYLINT", "DF12_FUTURE_ANNOTATIONS")
    }
    expected_option = f"--jobs={expected_jobs}"

    for name, command in commands.items():
        job_options = [
            argument for argument in command if argument.startswith("--jobs=")
        ]
        assert job_options == [expected_option], (
            f"{name} must receive exactly one {expected_option!r} argument: {command!r}"
        )

    for name in ("DF12_PYLINT", "DF12_FUTURE_ANNOTATIONS"):
        assert commands[name][: len(base)] == base, (
            f"{name} must inherit the full DF12_PYLINT_BASE command: "
            f"base={base!r}, command={commands[name]!r}"
        )

    assert commands["DF12_PYLINT"][len(base) :] == [
        f"--enable={_makefile_variable('DF12_PYLINT_MESSAGES')}"
    ], "DF12_PYLINT must append its configured message set to the base command."
    assert commands["DF12_FUTURE_ANNOTATIONS"][len(base) :] == [
        "--enable=C9112",
        "--ignore-paths=^tests/steps/test_.*_steps[.]py$",
    ], "the future-annotations command must append its own checks to the base."


@pytest.mark.parametrize(
    ("core_count", "expected_jobs"),
    [
        pytest.param(1, 2, id="cores-1-floor-2"),
        pytest.param(2, 2, id="cores-2-floor-2"),
        pytest.param(19, 2, id="cores-19-floor-2"),
        pytest.param(20, 2, id="cores-20-floor-2"),
        pytest.param(29, 2, id="cores-29-floor-2"),
        pytest.param(30, 3, id="cores-30-tenth-3"),
        pytest.param(39, 3, id="cores-39-tenth-3"),
        pytest.param(40, 4, id="cores-40-tenth-4"),
        pytest.param(128, 12, id="cores-128-tenth-12"),
    ],
)
def test_pylint_jobs_uses_tenth_of_controlled_core_count(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    core_count: int,
    expected_jobs: int,
) -> None:
    """Make's default keeps a two-worker floor and otherwise spends one tenth."""
    # These inherited values must not affect the no-override probe cases.
    monkeypatch.setenv("PYLINT_JOBS", "97")
    monkeypatch.setenv("MAKEFLAGS", "PYLINT_JOBS=98")
    monkeypatch.setenv("MFLAGS", "PYLINT_JOBS=96")
    monkeypatch.setenv("MAKEOVERRIDES", "PYLINT_JOBS=95")

    values = _run_pylint_jobs_probe(
        tmp_path,
        _JobsProbeSettings(nproc_result=str(core_count)),
    )

    assert values["PYLINT_JOBS"] == str(expected_jobs), (
        f"{core_count} cores must produce {expected_jobs} Pylint workers."
    )
    _assert_expanded_pylint_jobs(values, expected_jobs)


@pytest.mark.parametrize(
    ("nproc_result", "exit_code"),
    [
        pytest.param("", 1, id="nproc-exits-unsuccessfully"),
        pytest.param(None, 0, id="nproc-missing-from-isolated-path"),
    ],
)
def test_pylint_jobs_falls_back_to_two_when_nproc_is_unavailable(
    tmp_path: Path,
    nproc_result: str | None,
    exit_code: int,
) -> None:
    """A failed or missing `nproc` uses the documented two-worker fallback."""
    values = _run_pylint_jobs_probe(
        tmp_path,
        _JobsProbeSettings(
            nproc_result=nproc_result,
            nproc_exit_code=exit_code,
        ),
    )

    assert values["PYLINT_JOBS"] == "2", "the fallback must select two workers."
    _assert_expanded_pylint_jobs(values, 2)


@pytest.mark.parametrize(
    ("environment_jobs", "command_line_jobs", "expected_jobs"),
    [
        pytest.param("7", None, 7, id="environment-override"),
        pytest.param(None, "8", 8, id="command-line-override"),
        pytest.param("5", "9", 9, id="command-line-over-environment"),
    ],
)
def test_pylint_jobs_overrides_expand_to_all_three_commands(
    tmp_path: Path,
    environment_jobs: str | None,
    command_line_jobs: str | None,
    expected_jobs: int,
) -> None:
    """Environment and command-line overrides propagate with Make precedence."""
    values = _run_pylint_jobs_probe(
        tmp_path,
        _JobsProbeSettings(
            nproc_result="128",
            environment_jobs=environment_jobs,
            command_line_jobs=command_line_jobs,
        ),
    )

    assert values["PYLINT_JOBS"] == str(expected_jobs), (
        "Make must report the selected override value."
    )
    _assert_expanded_pylint_jobs(values, expected_jobs)


def test_pylint_reports_unparseable_modules() -> None:
    """The Pylint policy must not disable `syntax-error`."""
    config = tomllib.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    disabled = config["tool"]["pylint"]["messages control"]["disable"]
    assert "syntax-error" not in disabled, (
        "pyproject.toml must not disable syntax-error: a module the interpreter "
        f"cannot parse would then be skipped silently; disable={disabled!r}"
    )
