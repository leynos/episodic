"""Behavioural coverage for the local k3d preview CLI surface."""

import dataclasses as dc
import subprocess  # noqa: S404 - behavioural test invokes the local CLI.
import sys

from pytest_bdd import scenario, then, when


@dc.dataclass(slots=True)
class LocalK8sCliContext:
    """Shared CLI output for local preview BDD steps."""

    root_help: str = ""
    up_help: str = ""


@scenario(
    "../features/local_k8s_preview.feature",
    "Operators inspect the local preview command surface",
)
def test_local_preview_cli_surface() -> None:
    """Run the local preview CLI behavioural scenario."""


@when("an operator asks for local preview CLI help", target_fixture="cli_context")
def when_operator_asks_for_help() -> LocalK8sCliContext:
    """Capture root and subcommand help from the local preview CLI."""
    root_help = subprocess.run(  # noqa: S603 - test invokes known script with static arguments.
        [sys.executable, "scripts/local_k8s.py", "--help"],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout
    up_help = subprocess.run(  # noqa: S603 - test invokes known script with static arguments.
        [sys.executable, "scripts/local_k8s.py", "up", "--help"],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout
    return LocalK8sCliContext(root_help=root_help, up_help=up_help)


@then("the local preview CLI lists lifecycle commands")
def then_cli_lists_lifecycle_commands(cli_context: LocalK8sCliContext) -> None:
    """Assert lifecycle commands are visible from root help."""
    for command_name in ("up", "down", "status", "logs"):
        assert command_name in cli_context.root_help, (
            f"{command_name!r} must appear in local preview CLI help."
        )


@then("the up command documents dry-run and image-skip options")
def then_up_documents_operator_options(cli_context: LocalK8sCliContext) -> None:
    """Assert the important safe-preview options are visible."""
    assert "--dry-run" in cli_context.up_help, "up help must document dry-run mode."
    assert "--skip-image" in cli_context.up_help, (
        "up help must document the image-skip option."
    )
