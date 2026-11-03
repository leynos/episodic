"""Run Hecate from architecture enforcement tests.

The helpers in this module generate per-fixture TOML configuration files and
invoke the Hecate command-line interface (CLI) with captured output. Fixture
checks use explicit `--config`, `--package`, and `--root` arguments so each
test package is analysed in isolation. Production checks use the repository's
default `[tool.hecate]` configuration from `pyproject.toml`.

Typical fixture usage:

```python
config_path = write_fixture_config(tmp_path, "domain_imports_storage")
result = run_hecate_fixture_check("domain_imports_storage", config_path)
assert result.returncode == 1
```
"""

import subprocess  # ruff: ignore[suspicious-subprocess-import]  # Tests exercise the Hecate CLI contract.
import sys
import typing as typ
from pathlib import Path

from architecture_hecate_config_templates import (
    render_default_fixture_config,
    render_external_logging_fixture_config,
)

FIXTURE_ROOT: Path = Path(__file__).resolve().parent / "fixtures" / "architecture"
REPO_ROOT: Path = Path(__file__).resolve().parents[1]
BARREL_OUTBOUND_FIXTURE = "api_imports_star_reexported_outbound_adapter"
LOGGING_PORT_FIXTURE = "femtologging_outside_logging_port"
HECATE_TIMEOUT_SECONDS = 60
type FixturePolicyVariant = typ.Literal["default", "external_logging"]


def diagnostic_for_expectation(
    package_name: str,
    expected_text: str,
    rendered: str,
) -> str:
    """Normalize a fixture diagnostic for one expected substring.

    Parameters
    ----------
    package_name : str
        Directory name of the fixture package under `tests/fixtures/architecture`.
    expected_text : str
        Diagnostic substring asserted by the caller.
    rendered : str
        Combined standard output and standard error from Hecate.

    Returns
    -------
    str
        Rendered diagnostic, with the fixture package prefix removed only when
        checking the `femtologging` backend name.
    """
    if package_name != LOGGING_PORT_FIXTURE or expected_text != "femtologging":
        return rendered
    fixture_package = f"tests.fixtures.architecture.{package_name}"
    return rendered.replace(fixture_package, "")


class HecateInvocationError(RuntimeError):
    """Raised when the Hecate CLI process cannot be started or captured."""

    def __init__(
        self,
        *,
        package_name: str | None = None,
        timed_out: bool = False,
    ) -> None:
        """Build a contextual Hecate invocation failure."""
        if package_name is None:
            context = "production packages"
        else:
            context = f"fixture package {package_name!r}"
        message = (
            f"Hecate command timed out for {context}"
            if timed_out
            else f"failed to invoke Hecate for {context}"
        )
        super().__init__(message)


def write_fixture_config(
    tmp_path: Path,
    package_name: str,
    *,
    policy_variant: FixturePolicyVariant | None = None,
) -> Path:
    """Write a Hecate config for one architecture fixture package.

    Parameters
    ----------
    tmp_path : Path
        Temporary directory where the generated TOML file is written.
    package_name : str
        Directory name of the fixture package under `tests/fixtures/architecture`.
    policy_variant : FixturePolicyVariant | None, optional
        Fixture policy to render. By default, the femtologging boundary fixture
        uses `external_logging` and other fixtures use `default`.

    Returns
    -------
    Path
        Path to the generated Hecate TOML configuration file.

    Notes
    -----
    The `api_imports_star_reexported_outbound_adapter` fixture treats the
    package barrel as an outbound adapter because Hecate reports a star import
    from a package barrel as an import of the package module itself.
    """
    package = f"tests.fixtures.architecture.{package_name}"
    selected_policy = policy_variant
    if selected_policy is None:
        selected_policy = (
            "external_logging" if package_name == LOGGING_PORT_FIXTURE else "default"
        )
    config_path = tmp_path / f"{package_name}-hecate.toml"
    config_path.write_text(
        _fixture_config(
            package,
            treats_package_barrel_as_outbound=package_name == BARREL_OUTBOUND_FIXTURE,
            policy_variant=selected_policy,
        ),
        encoding="utf-8",
    )
    return config_path


def run_hecate_fixture_check(
    package_name: str,
    config_path: Path,
    *,
    python_executable: str | Path = sys.executable,
    output_format: str = "text",
) -> subprocess.CompletedProcess[str]:
    """Run Hecate against one architecture fixture package.

    Parameters
    ----------
    package_name : str
        Directory name of the fixture package under `tests/fixtures/architecture`.
    config_path : Path
        Path to the generated Hecate TOML configuration file.
    python_executable : str | Path
        Python executable used to invoke `python -m hecate`. Tests may inject a
        substitute executable when validating command construction.
    output_format : str
        Hecate output renderer to request. Supported values are `text` and
        `json`.

    Returns
    -------
    subprocess.CompletedProcess[str]
        Completed Hecate process with `stdout` and `stderr` captured.

    Raises
    ------
    HecateInvocationError
        Raised when the subprocess operation itself fails before Hecate can
        return an architecture-check exit code.

    Notes
    -----
    The command exercises the public CLI contract with `check=False` so tests
    can assert both passing and failing architecture checks.
    """
    package = f"tests.fixtures.architecture.{package_name}"
    package_root = FIXTURE_ROOT / package_name
    command = [
        str(python_executable),
        "-m",
        "hecate",
        "check",
        "--config",
        str(config_path),
        "--package",
        package,
        "--root",
        str(package_root),
        "--format",
        output_format,
    ]
    try:
        return subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]  # shell=False with trusted test args.
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=HECATE_TIMEOUT_SECONDS,
            cwd=REPO_ROOT,
        )
    except subprocess.TimeoutExpired as exc:
        raise HecateInvocationError(
            package_name=package_name,
            timed_out=True,
        ) from exc
    except (OSError, subprocess.SubprocessError) as exc:
        raise HecateInvocationError(package_name=package_name) from exc


def run_hecate_production_check(
    *,
    python_executable: str | Path = sys.executable,
) -> subprocess.CompletedProcess[str]:
    """Run Hecate against the production package using project config.

    Parameters
    ----------
    python_executable : str | Path
        Python executable used to invoke `python -m hecate`. Tests may inject a
        substitute executable when validating command construction.

    Returns
    -------
    subprocess.CompletedProcess[str]
        Completed Hecate process with `stdout` and `stderr` captured.

    Raises
    ------
    HecateInvocationError
        Raised when the subprocess operation itself fails before Hecate can
        return an architecture-check exit code.

    Notes
    -----
    This invokes Hecate using the repository's default configuration from
    `pyproject.toml`.
    """
    try:
        return subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true]  # shell=False with static arguments.
            [str(python_executable), "-m", "hecate", "check"],
            check=False,
            capture_output=True,
            text=True,
            timeout=HECATE_TIMEOUT_SECONDS,
            cwd=REPO_ROOT,
        )
    except subprocess.TimeoutExpired as exc:
        raise HecateInvocationError(timed_out=True) from exc
    except (OSError, subprocess.SubprocessError) as exc:
        raise HecateInvocationError from exc


def _fixture_config(
    package: str,
    *,
    treats_package_barrel_as_outbound: bool,
    policy_variant: FixturePolicyVariant,
) -> str:
    """Select one explicit fixture policy and render its TOML."""
    if policy_variant == "external_logging":
        return render_external_logging_fixture_config(package)
    return render_default_fixture_config(
        package,
        treats_package_barrel_as_outbound=treats_package_barrel_as_outbound,
    )
