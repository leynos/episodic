"""The CodeScene token reaches the publisher's upload, and publishers queue.

The upload is `upload-codescene-coverage`, a composite action. A composite
action's nested steps inherit the calling step's environment, so a token in
the upload step's `env`, or the job's, or the workflow's, reaches every step
inside the action. The publisher therefore keeps the token out of every `env`.
A check step publishes only whether the token exists, the upload's condition
reads that output, and the upload takes the token directly as an input.

The positive half matters as much as the prohibition. Deleting the token
entirely satisfies "no `env` holds it" while the upload's guard goes false and
publishing silently stops. So the token must be named exactly twice in the
publisher: in the check step's command and in the upload's input.

The publisher also serializes on one concurrency group per ref, without
cancelling a run in progress, so two publishers never race or abandon a
baseline write.
"""

import typing as typ

from tests.test_codescene_workflow_contract_support import (
    WORKFLOWS_DIRECTORY,
    load_workflow,
    mapping,
    workflow_jobs,
)

if typ.TYPE_CHECKING:
    import collections.abc as cabc

PUBLISHER = WORKFLOWS_DIRECTORY / "coverage-main.yml"
CREDENTIAL_NAME = "CS_ACCESS_TOKEN"
AVAILABILITY_STEP_ID = "codescene_token"
AVAILABILITY_COMMAND = (
    'echo "available=${{ secrets.CS_ACCESS_TOKEN != \'\' }}" >> "$GITHUB_OUTPUT"'
)
UPLOAD_CREDENTIAL_INPUT = "${{ secrets.CS_ACCESS_TOKEN }}"
PUBLISHER_GROUP = "coverage-main-${{ github.ref }}"


def _strings(value: object) -> cabc.Iterator[str]:
    """Yield every string in a parsed value, keys included."""
    match value:
        case str() as text:
            yield text
        case dict() as items:
            for key, item in items.items():
                yield from _strings(key)
                yield from _strings(item)
        case list() as sequence:
            for item in sequence:
                yield from _strings(item)
        case _:
            return


def _steps() -> list[dict[object, object]]:
    """Return every step of every publisher job, in order."""
    steps: list[dict[object, object]] = []
    for job in workflow_jobs(PUBLISHER).values():
        raw = mapping(job, subject="publisher job").get("steps", [])
        steps.extend(
            mapping(step, subject="publisher step")
            for step in typ.cast("list[object]", raw)
        )
    return steps


def _one(steps: list[dict[object, object]], key: str, value: object) -> int:
    """Return the index of the one step whose ``key`` equals ``value``."""
    found = [index for index, step in enumerate(steps) if step.get(key) == value]
    assert len(found) == 1, f"expected one step with {key}={value!r}, found {found}"
    return found[0]


def test_the_check_step_publishes_availability_and_nothing_else() -> None:
    """Run one command that writes a boolean, unconditionally, with no env.

    A condition on the check would leave its output unset whenever the
    condition was false, and an `env` on it would put the token back into an
    environment.
    """
    steps = _steps()
    check = steps[_one(steps, "id", AVAILABILITY_STEP_ID)]
    assert str(check.get("run", "")).strip() == AVAILABILITY_COMMAND, (
        f"the check must run exactly {AVAILABILITY_COMMAND!r}, got {check.get('run')!r}"
    )
    assert "if" not in check, "the check must run unconditionally"
    assert "env" not in check, "the check must declare no env"


def test_the_check_precedes_the_upload() -> None:
    """Publish the availability before the step that reads it."""
    steps = _steps()
    check = _one(steps, "id", AVAILABILITY_STEP_ID)
    upload = _one(steps, "name", "Upload coverage data to CodeScene")
    assert check < upload, "the token check must run before the upload"


def test_no_environment_on_the_publisher_holds_the_token() -> None:
    """Keep the token out of the workflow, job and step environments."""
    document = load_workflow(PUBLISHER)
    envs: list[object] = [document.get("env")]
    envs += [
        mapping(job, subject="publisher job").get("env")
        for job in workflow_jobs(PUBLISHER).values()
    ]
    envs += [step.get("env") for step in _steps()]
    holders = [env for env in envs if any(CREDENTIAL_NAME in s for s in _strings(env))]
    assert holders == [], (
        f"no env on the publisher may name {CREDENTIAL_NAME}, found {holders!r}; a "
        "composite action's nested steps inherit the calling step's env"
    )


def test_the_token_appears_exactly_where_it_is_used() -> None:
    """Name the token in the check's command and the upload's input, only."""
    mentions = sorted(
        text.strip()
        for text in _strings(load_workflow(PUBLISHER))
        if CREDENTIAL_NAME in text
    )
    assert mentions == sorted([AVAILABILITY_COMMAND, UPLOAD_CREDENTIAL_INPUT]), (
        f"the publisher must name {CREDENTIAL_NAME} exactly in the check command and "
        f"the upload input, got {mentions!r}"
    )


def test_publishers_queue_on_one_group_per_ref() -> None:
    """Serialize publishers per ref, and never cancel one in progress.

    Without a group two runs race to write the baseline; with
    `cancel-in-progress: true` the newer run abandons the older one's write
    half done.
    """
    concurrency = mapping(
        load_workflow(PUBLISHER).get("concurrency"), subject="publisher concurrency"
    )
    assert concurrency.get("group") == PUBLISHER_GROUP, (
        f"the publisher group must be {PUBLISHER_GROUP!r}, "
        f"got {concurrency.get('group')!r}"
    )
    assert concurrency.get("cancel-in-progress") is False, (
        "the publisher must not cancel a run in progress, got "
        f"{concurrency.get('cancel-in-progress')!r}"
    )
