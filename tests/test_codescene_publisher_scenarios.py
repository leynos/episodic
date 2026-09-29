"""Whether the publisher uploads, for each token, event and ref it can meet.

The other publisher contracts pin the check command and the upload's
condition as text. This one runs them. The check step's own script runs under
`bash` with its secret expression rendered as GitHub renders it, and the
output it writes feeds the job's and the upload's declared `if:` conditions.
So the decision is read end to end from the workflow file: an absent token
skips the upload, and so does any ref but `main`, on a push or a dispatch
alike.

The conditions are evaluated by a deliberately tiny reader: `&&`-joined
`==`/`!=` comparisons of a `github.<field>` or `steps.<id>.outputs.<name>`
reference against a single-quoted literal. Anything else raises, because a
reader that answered False for an expression it could not parse would pass
the no-upload cases for the wrong reason.

Running the workflow itself, under `act` or on a runner, would need the
CodeScene token; the upload's real proof is the publisher run on the merge
commit.
"""

import re
import shutil
import subprocess  # noqa: S404  # The check step's own script is under test.
import typing as typ

import pytest

from tests.test_codescene_workflow_contract_support import (
    WORKFLOWS_DIRECTORY,
    mapping,
    workflow_jobs,
    workflow_steps,
)

if typ.TYPE_CHECKING:
    import pathlib as pl

PUBLISHER = WORKFLOWS_DIRECTORY / "coverage-main.yml"
JOB = "coverage-upload"
AVAILABILITY_STEP_ID = "codescene_token"
UPLOAD_ACTION = "upload-codescene-coverage"
SKIP_NOTICE_STEP = "Report a skipped CodeScene upload"
# The check's expression, which GitHub renders to `true` or `false` before the
# shell runs.
AVAILABILITY_EXPRESSION = "${{ secrets.CS_ACCESS_TOKEN != '' }}"
AVAILABILITY_OUTPUT = f"steps.{AVAILABILITY_STEP_ID}.outputs.available"
TRUNK = "refs/heads/main"
BRANCH = "refs/heads/feature"
_COMPARISON = re.compile(
    r"\A(?P<reference>github\.[a-z_]+|steps\.[A-Za-z_][\w-]*\.outputs\.[A-Za-z_][\w-]*)"
    r"\s*(?P<operator>==|!=)\s*'(?P<literal>[^']*)'\Z"
)


class Scenario(typ.NamedTuple):
    """One run the publisher can meet, and whether it should upload."""

    has_token: bool
    event_name: str
    ref: str
    uploads: bool


def _evaluate(expression: object, context: dict[str, str]) -> bool:
    """Return whether an `if:` holds in ``context``; None always holds.

    Every term is evaluated before the verdicts combine, so a term outside the
    grammar raises even after a false one.

    Returns
    -------
    bool
        Whether every `&&`-joined comparison holds.
    """
    if expression is None:
        return True
    verdicts = []
    for term in str(expression).split("&&"):
        match = _COMPARISON.match(term.strip())
        assert match is not None, f"{term!r} in {expression!r} is outside the grammar"
        value = context[match["reference"]]
        equal = value == match["literal"]
        verdicts.append(equal if match["operator"] == "==" else not equal)
    return all(verdicts)


def _published_availability(tmp_path: pl.Path, *, has_token: bool) -> str:
    """Run the check step's script and return the `available` it writes."""
    check = next(
        step
        for step in workflow_steps(PUBLISHER, JOB)
        if step.get("id") == AVAILABILITY_STEP_ID
    )
    script = str(check.get("run", ""))
    assert AVAILABILITY_EXPRESSION in script, (
        f"the check must render {AVAILABILITY_EXPRESSION!r}, got {script!r}"
    )
    output = tmp_path / "github_output"
    bash = shutil.which("bash")
    assert bash is not None, "bash must be installed to run the check step"
    rendered = script.replace(AVAILABILITY_EXPRESSION, str(has_token).lower())
    subprocess.run(  # noqa: S603  # The workflow's own script, rendered here.
        [bash, "-c", rendered],
        check=True,
        env={"PATH": "/usr/bin:/bin", "GITHUB_OUTPUT": str(output)},
    )
    outputs = dict(line.split("=", 1) for line in output.read_text().splitlines())
    return outputs["available"]


SCENARIOS = [
    pytest.param(
        Scenario(has_token=True, event_name="push", ref=TRUNK, uploads=True),
        id="push-to-main",
    ),
    pytest.param(
        Scenario(
            has_token=True, event_name="workflow_dispatch", ref=TRUNK, uploads=True
        ),
        id="dispatch-main",
    ),
    pytest.param(
        Scenario(has_token=False, event_name="push", ref=TRUNK, uploads=False),
        id="no-token",
    ),
    pytest.param(
        Scenario(
            has_token=False,
            event_name="workflow_dispatch",
            ref=TRUNK,
            uploads=False,
        ),
        id="no-token-dispatch",
    ),
    pytest.param(
        Scenario(
            has_token=True,
            event_name="workflow_dispatch",
            ref=BRANCH,
            uploads=False,
        ),
        id="dispatch-branch",
    ),
]


def _upload_step() -> dict[object, object]:
    """Return the publisher's CodeScene upload step."""
    return next(
        step
        for step in workflow_steps(PUBLISHER, JOB)
        if UPLOAD_ACTION in str(step.get("uses", ""))
    )


def _job_decision(tmp_path: pl.Path, scenario: Scenario) -> tuple[bool, dict[str, str]]:
    """Return whether the job runs, and the context its steps are judged in.

    Returns
    -------
    tuple[bool, dict[str, str]]
        The job condition's verdict and the evaluation context, including the
        availability the check step's own script writes.
    """
    job = mapping(workflow_jobs(PUBLISHER).get(JOB), subject=f"{PUBLISHER} {JOB}")
    context = {
        "github.event_name": scenario.event_name,
        "github.ref": scenario.ref,
        AVAILABILITY_OUTPUT: _published_availability(
            tmp_path, has_token=scenario.has_token
        ),
    }
    return _evaluate(job.get("if"), context), context


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_the_publisher_uploads_only_with_a_token_on_main(
    tmp_path: pl.Path, scenario: Scenario
) -> None:
    """Upload exactly when the token exists and the run is on `main`.

    Both the job's condition and the upload step's must hold. An absent token
    must skip rather than fail, and a dispatch from a feature branch must never
    upload that branch's coverage as the trunk's.
    """
    job_runs, context = _job_decision(tmp_path, scenario)
    decided = job_runs and _evaluate(_upload_step().get("if"), context)
    assert decided is scenario.uploads, (
        f"{scenario}: expected upload={scenario.uploads}, the workflow decides "
        f"{decided}"
    )


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_a_skipped_upload_is_reported_without_the_secret(
    tmp_path: pl.Path, scenario: Scenario
) -> None:
    """Report the skip exactly when the job runs and the upload does not.

    A skipped step reads as success, so an absent token would otherwise go
    unnoticed. The notice reads only the check's boolean output and names no
    secret, so it cannot print the token.
    """
    notice = next(
        step
        for step in workflow_steps(PUBLISHER, JOB)
        if step.get("name") == SKIP_NOTICE_STEP
    )
    command = str(notice.get("run", ""))
    assert "secrets." not in command, f"the notice must read no secret: {command!r}"
    assert "::notice" in command, f"the notice must annotate the run: {command!r}"
    job_runs, context = _job_decision(tmp_path, scenario)
    reported = job_runs and _evaluate(notice.get("if"), context)
    uploads = job_runs and _evaluate(_upload_step().get("if"), context)
    assert reported is (job_runs and not uploads), (
        f"{scenario}: the skip notice must run exactly when the job runs and "
        f"the upload does not; it runs={reported}, upload={uploads}"
    )
