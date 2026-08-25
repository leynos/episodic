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
import typing as typ
from pathlib import Path

FIXTURE_ROOT: Path = Path(__file__).resolve().parent / "fixtures" / "architecture"
REPO_ROOT: Path = Path(__file__).resolve().parents[1]
COMPOSITION_ROOT_GROUPS: tuple[str, ...] = (
    "application",
    "composition_root",
    "domain",
    "inbound_adapter",
    "outbound_adapter",
)
DOMAIN_GROUPS: tuple[str, ...] = ("domain",)
APPLICATION_GROUPS: tuple[str, ...] = ("application", "domain")
INBOUND_ADAPTER_GROUPS: tuple[str, ...] = ("inbound_adapter", "application", "domain")
OUTBOUND_ADAPTER_GROUPS: tuple[str, ...] = (
    "outbound_adapter",
    "application",
    "domain",
)
BARREL_OUTBOUND_FIXTURE = "api_imports_star_reexported_outbound_adapter"
LOGGING_PORT_FIXTURE = "femtologging_outside_logging_port"
HECATE_TIMEOUT_SECONDS = 60
type FixturePolicyVariant = typ.Literal["default", "external_logging"]


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
    policy_variant: FixturePolicyVariant = "default",
) -> Path:
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
            treats_package_barrel_as_outbound=package_name == BARREL_OUTBOUND_FIXTURE,
            policy_variant=policy_variant,
        ),
        encoding="utf-8",
    )
    return config_path


def run_hecate_fixture_check(
    package_name: str,
    config_path: Path,
    *,
    python_executable: str | Path = sys.executable,
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
    ]
    try:
        return subprocess.run(  # noqa: S603  # shell=False with trusted test args.
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
        return subprocess.run(  # noqa: S603  # shell=False with static arguments.
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
    """Return fixture-specific Hecate TOML."""
    if policy_variant == "external_logging":
        return _external_logging_fixture_config(package)
    outbound_prefixes = (
        f'"{package}.storage", "{package}"'
        if treats_package_barrel_as_outbound
        else f'"{package}.storage"'
    )
    composition_root_allowed = _toml_string_array(COMPOSITION_ROOT_GROUPS)
    domain_allowed = _toml_string_array(DOMAIN_GROUPS)
    application_allowed = _toml_string_array(APPLICATION_GROUPS)
    inbound_adapter_allowed = _toml_string_array(INBOUND_ADAPTER_GROUPS)
    outbound_adapter_allowed = _toml_string_array(OUTBOUND_ADAPTER_GROUPS)
    return textwrap.dedent(
        f"""\
        [tool.hecate]
        root_packages = ["{package}"]
        default_rule_id = "ARCH001"

        [[tool.hecate.groups]]
        name = "composition_root"
        prefixes = ["{package}.runtime"]
        allowed = {composition_root_allowed}

        [[tool.hecate.groups]]
        name = "domain"
        prefixes = ["{package}.domain"]
        allowed = {domain_allowed}

        [[tool.hecate.groups]]
        name = "application"
        prefixes = ["{package}.service"]
        allowed = {application_allowed}

        [[tool.hecate.groups]]
        name = "inbound_adapter"
        prefixes = ["{package}.api"]
        allowed = {inbound_adapter_allowed}

        [[tool.hecate.groups]]
        name = "outbound_adapter"
        prefixes = [{outbound_prefixes}]
        allowed = {outbound_adapter_allowed}
        """
    )


def _external_logging_fixture_config(package: str) -> str:
    """Return a fixture policy that enforces the femtologging boundary."""
    return textwrap.dedent(
        f"""\
        [tool.hecate]
        root_packages = ["{package}"]
        default_rule_id = "ARCH001"
        include_external_packages = true

        [[tool.hecate.groups]]
        name = "logging_port"
        prefixes = ["{package}.logging"]
        allowed = ["logging_port", "logging_backend"]

        [[tool.hecate.groups]]
        name = "logging_backend"
        prefixes = ["femtologging"]
        allowed = ["logging_backend"]

        [[tool.hecate.groups]]
        name = "external_libraries"
        prefixes = [
            "alembic",
            "celery",
            "falcon",
            "httpx",
            "langgraph",
            "openai",
            "pydantic",
            "sqlalchemy",
        ]
        allowed = ["external_libraries"]

        [[tool.hecate.groups]]
        name = "composition_root"
        prefixes = ["{package}.runtime"]
        allowed = [
            "application",
            "composition_root",
            "domain",
            "external_libraries",
            "inbound_adapter",
            "logging_port",
            "outbound_adapter",
        ]

        [[tool.hecate.groups]]
        name = "domain"
        prefixes = ["{package}.domain"]
        allowed = ["domain", "external_libraries", "logging_port"]

        [[tool.hecate.groups]]
        name = "application"
        prefixes = ["{package}.service"]
        allowed = ["application", "domain", "external_libraries", "logging_port"]

        [[tool.hecate.groups]]
        name = "inbound_adapter"
        prefixes = ["{package}.api"]
        allowed = [
            "application",
            "domain",
            "external_libraries",
            "inbound_adapter",
            "logging_port",
        ]

        [[tool.hecate.groups]]
        name = "outbound_adapter"
        prefixes = ["{package}.storage"]
        allowed = [
            "application",
            "domain",
            "external_libraries",
            "logging_port",
            "outbound_adapter",
        ]
        """
    )


def _toml_string_array(values: tuple[str, ...]) -> str:
    """Return a TOML array of quoted strings."""
    return "[" + ", ".join(f'"{value}"' for value in values) + "]"
