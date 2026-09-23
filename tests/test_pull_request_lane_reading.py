"""Contract tests for reading the pull-request lane as a call closure.

`workflow_call_graph` reads reference shapes and closes a call graph; the
support module reads the repository into that graph. The shape cases run on
the pure reader. The tree cases build small workflow trees and point the
support module at them, because no workflow in this repository calls another
today, so its own files cannot show the traversal working, or failing.
"""

import typing as typ

import pytest

from tests import test_codescene_workflow_contract_support as support
from tests.test_codescene_workflow_contract import PULL_REQUEST_TRIGGERS
from tests.test_codescene_workflow_contract_support import workflows_reachable_from
from tests.workflow_call_graph import UnresolvedWorkflowCallError, local_workflow_name

if typ.TYPE_CHECKING:
    import pathlib as pl


@pytest.mark.parametrize(
    ("reference", "expected"),
    [
        ("./.github/workflows/ci.yml", "ci.yml"),
        (".github/workflows/ci.yml", "ci.yml"),
        ("$/.github/workflows/ci.yml", "ci.yml"),
        ("$/.github/workflows/nested/ci.yml", None),
        ("./.github/workflows/nested/ci.yml", None),
        ("./.github/actions/setup", None),
        ("leynos/episodic/.github/workflows/ci.yml@main", None),
        ("./.github/workflows/", None),
    ],
)
def test_a_local_workflow_call_is_read_by_shape(
    reference: str, expected: str | None
) -> None:
    """Follow a call exactly when it names a file under the workflow directory.

    Both documented same-repository prefixes, `./` and `$/`, are followed; a
    reader knowing only one drops callers written the other way. One that
    accepted any path would follow a subdirectory GitHub never reads.
    """
    resolved = local_workflow_name(reference)
    assert resolved == expected, (
        f"{reference!r} must read as {expected!r}, got {resolved!r}"
    )


def test_the_lane_follows_calls_transitively(
    tmp_path: pl.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reach a `workflow_call` workflow through a called one, and nothing else.

    No workflow here calls another today, so the repository's own files cannot
    show the traversal working; a tree of three workflows can. The uncalled
    reusable workflow stays out, so a complying repository is not failed.
    """
    directory = tmp_path / ".github" / "workflows"
    directory.mkdir(parents=True)
    call = "jobs:\n  call:\n    uses: ./.github/workflows/{}\n    secrets: inherit\n"
    (directory / "ci.yml").write_text("on: pull_request\n" + call.format("middle.yml"))
    (directory / "middle.yml").write_text(
        "on: workflow_call\n" + call.format("probe.yml")
    )
    for name in ("probe.yml", "uncalled.yml"):
        (directory / name).write_text("on: workflow_call\njobs: {}\n")
    monkeypatch.setattr(support, "WORKFLOWS_DIRECTORY", directory)

    reached = {path.name for path in workflows_reachable_from(PULL_REQUEST_TRIGGERS)}
    assert reached == {"ci.yml", "middle.yml", "probe.yml"}, (
        f"the lane must be the transitive closure of calls, got {sorted(reached)}"
    )


def test_a_local_call_to_a_missing_workflow_fails(
    tmp_path: pl.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Refuse to drop a local call the closure cannot read out of the lane.

    Read end to end through the repository reader, so the refusal is shown at
    the boundary the contract uses, not only in the pure closure.
    """
    directory = tmp_path / ".github" / "workflows"
    directory.mkdir(parents=True)
    (directory / "ci.yml").write_text(
        "on: pull_request\njobs:\n  call:\n    uses: ./.github/workflows/gone.yml\n"
    )
    monkeypatch.setattr(support, "WORKFLOWS_DIRECTORY", directory)
    with pytest.raises(UnresolvedWorkflowCallError, match=r"gone\.yml"):
        workflows_reachable_from(PULL_REQUEST_TRIGGERS)


def test_an_unreadable_workflow_names_its_file(
    tmp_path: pl.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fail on malformed YAML with an error that names the workflow."""
    directory = tmp_path / ".github" / "workflows"
    directory.mkdir(parents=True)
    (directory / "broken.yml").write_text("on: [pull_request\n")
    monkeypatch.setattr(support, "WORKFLOWS_DIRECTORY", directory)
    with pytest.raises(support.WorkflowReadError, match=r"broken\.yml"):
        workflows_reachable_from(PULL_REQUEST_TRIGGERS)
