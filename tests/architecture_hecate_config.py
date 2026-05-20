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

import subprocess  # noqa: S404  # Tests exercise the Hecate CLI contract.
import sys
import textwrap
from pathlib import Path

FIXTURE_ROOT: Path = Path(__file__).resolve().parent / "fixtures" / "architecture"


def write_fixture_config(tmp_path: Path, package_name: str) -> Path:
    """Write a Hecate config for one architecture fixture package.

    Parameters
    ----------
    tmp_path : Path
        Temporary directory where the generated TOML file is written.
    package_name : str
        Directory name of the fixture package under `tests/fixtures/architecture`.

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
    config_path = tmp_path / f"{package_name}-hecate.toml"
    config_path.write_text(
        _fixture_config(
            package,
            treats_package_barrel_as_outbound=(
                package_name == "api_imports_star_reexported_outbound_adapter"
            ),
        ),
        encoding="utf-8",
    )
    return config_path


def run_hecate_fixture_check(
    package_name: str,
    config_path: Path,
) -> subprocess.CompletedProcess[str]:
    """Run Hecate against one architecture fixture package.

    Parameters
    ----------
    package_name : str
        Directory name of the fixture package under `tests/fixtures/architecture`.
    config_path : Path
        Path to the generated Hecate TOML configuration file.

    Returns
    -------
    subprocess.CompletedProcess[str]
        Completed Hecate process with `stdout` and `stderr` captured.

    Notes
    -----
    The command exercises the public CLI contract with `check=False` so tests
    can assert both passing and failing architecture checks.
    """
    package = f"tests.fixtures.architecture.{package_name}"
    package_root = FIXTURE_ROOT / package_name
    return subprocess.run(  # noqa: S603  # shell=False with trusted test args.
        [
            sys.executable,
            "-m",
            "hecate",
            "check",
            "--config",
            str(config_path),
            "--package",
            package,
            "--root",
            str(package_root),
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def run_hecate_production_check() -> subprocess.CompletedProcess[str]:
    """Run Hecate against the production package using project config.

    Returns
    -------
    subprocess.CompletedProcess[str]
        Completed Hecate process with `stdout` and `stderr` captured.

    Notes
    -----
    This invokes Hecate using the repository's default configuration from
    `pyproject.toml`.
    """
    return subprocess.run(  # noqa: S603  # shell=False with static arguments.
        [sys.executable, "-m", "hecate", "check"],
        check=False,
        capture_output=True,
        text=True,
    )


def _fixture_config(package: str, *, treats_package_barrel_as_outbound: bool) -> str:
    """Return fixture-specific Hecate TOML."""
    outbound_prefixes = (
        f'"{package}.storage", "{package}"'
        if treats_package_barrel_as_outbound
        else f'"{package}.storage"'
    )
    return textwrap.dedent(
        f"""\
        [tool.hecate]
        root_packages = ["{package}"]
        default_rule_id = "ARCH001"

        [[tool.hecate.groups]]
        name = "composition_root"
        prefixes = ["{package}.runtime"]
        allowed = [
            "application",
            "composition_root",
            "domain",
            "inbound_adapter",
            "outbound_adapter",
        ]

        [[tool.hecate.groups]]
        name = "domain"
        prefixes = ["{package}.domain"]
        allowed = ["domain"]

        [[tool.hecate.groups]]
        name = "application"
        prefixes = ["{package}.service"]
        allowed = ["application", "domain"]

        [[tool.hecate.groups]]
        name = "inbound_adapter"
        prefixes = ["{package}.api"]
        allowed = ["inbound_adapter", "application", "domain"]

        [[tool.hecate.groups]]
        name = "outbound_adapter"
        prefixes = [{outbound_prefixes}]
        allowed = ["outbound_adapter", "application", "domain"]
        """
    )
