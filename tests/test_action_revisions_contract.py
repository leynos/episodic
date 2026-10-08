"""Contract for the approved shared-action revisions and retired pins.

The shared CV-005 contracts hold the coverage workflows' shape; they do not
know which nested third-party actions GitHub has retired. A composite action
that reaches a retired pin fails while Actions prepares the job, before its
first step runs, so this repository records each approved shared-action
revision with the actions nested inside it and refuses any revision the record
does not carry or any retired pin anywhere in the workflows.
"""

import json
import typing as typ

from hypothesis import given
from hypothesis import strategies as st

from tests import workflow_reading
from tests.workflow_reading import (
    REPOSITORY_ROOT,
    Mapping,
    mapping,
    uses_in,
    workflow_paths,
    workflow_uses,
)

if typ.TYPE_CHECKING:
    import pathlib as pl

    import pytest

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
    """No parsed `uses` value in a workflow equals a retired pin in the record.

    A retired pin mentioned only in a YAML comment is inert and does not fail.
    """
    retired = mapping(_revision_fixture()["retired"], subject="retired action pins")
    assert retired, (
        "the record must name at least one retired pin, or this asserts nothing"
    )
    for workflow_path in workflow_paths():
        for reference in uses_in(workflow_reading.load_workflow(workflow_path)):
            assert reference not in retired, (
                f"{workflow_path} references retired pin {reference}"
            )


def test_a_quoted_reference_splits_like_an_unquoted_one(
    tmp_path: pl.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A quoted publisher reference is split into action and revision as written.

    The workflow below is real YAML text, one quoted and one unquoted
    reference, read through the same loader and splitting the contract uses, so
    a regex over the raw text (which kept the quotes) would fail here.
    """
    workflow = tmp_path / "w.yml"
    workflow.write_text(
        "name: w\n"
        "on: pull_request\n"
        "jobs:\n"
        "  a:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        f"      - uses: '{GENERATE_COVERAGE_ACTION}@abc'\n"
        f"      - uses: {UPLOAD_CODESCENE_ACTION}@def\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(workflow_reading, "workflow_paths", lambda: (workflow,))

    assert workflow_uses() == [
        (GENERATE_COVERAGE_ACTION, "abc"),
        (UPLOAD_CODESCENE_ACTION, "def"),
    ], "quoted and unquoted references must split identically"


_REFERENCES = st.text(min_size=1, max_size=12)
_KEYS = st.text(max_size=6).filter(lambda key: key != "uses")
_LEAVES = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(),
    st.text(max_size=8),
    _REFERENCES.map(lambda reference: {"uses": reference}),
    st.integers().map(lambda number: {"uses": number}),
)
_WORKFLOWS = st.recursive(
    _LEAVES,
    lambda children: st.one_of(
        st.lists(children, max_size=4),
        st.dictionaries(_KEYS, children, max_size=4),
        st.tuples(_REFERENCES, children).map(
            lambda pair: {"uses": pair[0], "with": pair[1]}
        ),
    ),
    max_leaves=25,
)


def _oracle(value: object) -> list[str]:
    """List every string stored under a `uses` key, by explicit stack walk.

    Deliberately not recursive, so a recursion slip in `uses_in` (a skipped
    branch, a stop at a `uses` sibling, a wrong type test) cannot be shared by
    the oracle.

    Parameters
    ----------
    value : object
        A parsed YAML value.

    Returns
    -------
    list[str]
        The `uses` strings, in no particular order.
    """
    found: list[str] = []
    pending = [value]
    while pending:
        node = pending.pop()
        match node:
            case dict():
                for key, item in node.items():
                    if key == "uses" and isinstance(item, str):
                        found.append(item)
                    if isinstance(item, dict | list):
                        pending.append(item)
            case list():
                pending.extend(node)
    return found


@given(workflow=_WORKFLOWS)
def test_uses_in_finds_exactly_the_string_uses_values_at_any_depth(
    workflow: object,
) -> None:
    """`uses_in` returns every string under a `uses` key, once, and nothing else.

    Generated trees mix lists, mappings, scalars, `uses` leaves with string and
    integer values, and mappings that carry both a `uses` string and a nested
    `with` subtree, so a reference sits at a different depth and beside
    different siblings on each example. The result is compared, as a multiset,
    with an independent iterative oracle.
    """
    assert sorted(uses_in(workflow)) == sorted(_oracle(workflow)), (
        "uses_in must match the oracle on every generated tree"
    )
