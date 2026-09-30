"""Contract for the approved shared-action revisions and retired pins.

The shared CV-005 contracts hold the coverage workflows' shape; they do not
know which nested third-party actions GitHub has retired. A composite action
that reaches a retired pin fails while Actions prepares the job, before its
first step runs, so this repository records each approved shared-action
revision with the actions nested inside it and refuses any revision the record
does not carry or any retired pin anywhere in the workflows.
"""

import json

from tests.workflow_reading import (
    REPOSITORY_ROOT,
    Mapping,
    mapping,
    workflow_paths,
    workflow_uses,
)

GENERATE_COVERAGE_ACTION = "leynos/shared-actions/.github/actions/generate-coverage"
UPLOAD_CODESCENE_ACTION = (
    "leynos/shared-actions/.github/actions/upload-codescene-coverage"
)
ACTION_REVISIONS = (
    REPOSITORY_ROOT / "tests" / "support" / "approved_action_revisions.json"
)
TRACKED_ACTIONS = frozenset({GENERATE_COVERAGE_ACTION, UPLOAD_CODESCENE_ACTION})


def _revision_fixture() -> Mapping:
    """Return the offline approved-action and retired-pin record."""
    fixture = json.loads(ACTION_REVISIONS.read_text(encoding="utf-8"))
    return mapping(fixture, subject="approved action revisions fixture")


def test_tracked_composites_carry_no_retired_dependency() -> None:
    """Every tracked revision is recorded and reaches no retired pin.

    A Dependabot bump of a tracked action fails here until the fixture records
    the new revision's nested pins; that failure is the review step.
    """
    fixture = _revision_fixture()
    retired = mapping(fixture["retired"], subject="retired action pins")
    approved = mapping(fixture["approved"], subject="approved action pins")

    tracked_references = [
        (action, revision)
        for action, revision in workflow_uses()
        if action in TRACKED_ACTIONS
    ]
    assert tracked_references, (
        "coverage workflows must reference tracked shared actions"
    )
    for action, revision in tracked_references:
        action_revisions = mapping(approved.get(action), subject=f"approved {action}")
        assert revision in action_revisions, (
            f"{action}@{revision} is not recorded in "
            f"{ACTION_REVISIONS.relative_to(REPOSITORY_ROOT)}"
        )
        details = mapping(action_revisions[revision], subject=f"{action}@{revision}")
        nested_uses = mapping(
            details["nested_uses"], subject=f"{action}@{revision} dependencies"
        )
        for dependency in nested_uses:
            assert dependency not in retired, (
                f"{action}@{revision} reaches retired dependency {dependency}"
            )


def test_retired_pins_do_not_reappear_in_workflows() -> None:
    """Every retired pin in the checked-in record remains absent from workflows."""
    retired = mapping(_revision_fixture()["retired"], subject="retired action pins")
    assert retired, (
        "the record must name at least one retired pin, or this asserts nothing"
    )
    for workflow_path in workflow_paths():
        text = workflow_path.read_text(encoding="utf-8")
        for pin in retired:
            assert str(pin) not in text, f"{workflow_path} references retired pin {pin}"
