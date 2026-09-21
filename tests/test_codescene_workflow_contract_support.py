"""Readers for GitHub Actions workflow documents, shared by contract tests.

These helpers parse the repository's own workflows. They exist as a module of
their own so the contracts that use them stay within the repository's file
length limit, and so a second contract can read workflows the same way rather
than growing a second parser.
"""

import pathlib as pl
import re
import typing as typ

import yaml

REPOSITORY_ROOT = pl.Path(__file__).resolve().parents[1]
WORKFLOWS_DIRECTORY = REPOSITORY_ROOT / ".github" / "workflows"
Workflow = dict[typ.Any, typ.Any]
Step = dict[typ.Any, typ.Any]


def mapping(value: object, *, subject: str) -> Workflow:
    """Return a mapping value, failing with context for malformed YAML.

    Parameters
    ----------
    value : object
        Value parsed from a workflow document.
    subject : str
        Description of the value used in the failure message.

    Returns
    -------
    Workflow
        The value, once it is known to be a mapping.
    """
    assert isinstance(value, dict), f"{subject} must be a mapping, got {value!r}"
    return value


def load_workflow(path: pl.Path) -> Workflow:
    """Parse one workflow using PyYAML's GitHub-compatible key handling.

    Parameters
    ----------
    path : pl.Path
        Workflow document to parse.

    Returns
    -------
    Workflow
        The parsed document.
    """
    return mapping(yaml.safe_load(path.read_text(encoding="utf-8")), subject=str(path))


def workflow_paths() -> tuple[pl.Path, ...]:
    """Return every workflow whose steps could invoke an external action.

    Returns
    -------
    tuple[pl.Path, ...]
        Workflow documents under the repository's workflow directory, sorted.
    """
    return tuple(
        sorted((
            *WORKFLOWS_DIRECTORY.glob("*.yml"),
            *WORKFLOWS_DIRECTORY.glob("*.yaml"),
        ))
    )


def workflow_triggers(path: pl.Path) -> frozenset[str]:
    """Return one workflow's event names.

    PyYAML resolves an unquoted ``on:`` key to the boolean ``True``, so a
    reader that consults only the string key sees no events at all and lets
    every trigger-scoped contract pass over an empty set. Both keys are read.

    Parameters
    ----------
    path : pl.Path
        Workflow document to read.

    Returns
    -------
    frozenset[str]
        Every event name the workflow declares, from either spelling of the
        trigger key.
    """
    workflow = load_workflow(path)
    events: set[str] = set()
    for key in ("on", True):
        if key not in workflow:
            continue
        value = workflow[key]
        if isinstance(value, dict | list):
            events.update(str(event) for event in value)
        else:
            events.add(str(value))
    return frozenset(events)


def trigger_config(path: pl.Path, event: str) -> Workflow | None:
    """Return one event's configuration from a workflow's trigger mapping.

    Parameters
    ----------
    path : pl.Path
        Workflow document to read.
    event : str
        Event name whose configuration is wanted.

    Returns
    -------
    Workflow | None
        The event's mapping, or None when the event is absent or carries no
        configuration of its own.
    """
    workflow = load_workflow(path)
    for key in ("on", True):
        value = workflow.get(key)
        if isinstance(value, dict) and event in value:
            configuration = value[event]
            return configuration if isinstance(configuration, dict) else None
    return None


def workflow_jobs(path: pl.Path) -> Workflow:
    """Return the jobs mapping from one parsed workflow.

    Parameters
    ----------
    path : pl.Path
        Workflow document to read.

    Returns
    -------
    Workflow
        The document's jobs mapping.
    """
    workflow = load_workflow(path)
    return mapping(workflow.get("jobs"), subject=f"{path} jobs")


def workflow_steps(path: pl.Path, job_name: str) -> list[Step]:
    """Return the ordered steps from one workflow job.

    Parameters
    ----------
    path : pl.Path
        Workflow document to read.
    job_name : str
        Job whose steps are wanted.

    Returns
    -------
    list[Step]
        The job's steps, in declaration order.
    """
    job = mapping(workflow_jobs(path).get(job_name), subject=f"{path} {job_name}")
    steps = job.get("steps")
    assert isinstance(steps, list), f"{path} {job_name} must declare steps"
    return [mapping(step, subject=f"{path} {job_name} step") for step in steps]


def named_step(path: pl.Path, job_name: str, name: str) -> Step:
    """Return one uniquely named step from a workflow job.

    Parameters
    ----------
    path : pl.Path
        Workflow document to read.
    job_name : str
        Job containing the step.
    name : str
        Step name, which must identify exactly one step.

    Returns
    -------
    Step
        The named step.
    """
    matches = [
        step for step in workflow_steps(path, job_name) if step.get("name") == name
    ]
    assert len(matches) == 1, f"{path} {job_name} must contain one {name!r} step"
    return matches[0]


def all_workflow_steps() -> list[tuple[pl.Path, str, Step]]:
    """Return every job step from every repository workflow.

    Returns
    -------
    list[tuple[pl.Path, str, Step]]
        One entry per step, carrying its workflow path and job name.
    """
    collected: list[tuple[pl.Path, str, Step]] = []
    for path in workflow_paths():
        for job_name, job in workflow_jobs(path).items():
            if not isinstance(job, dict) or not isinstance(job.get("steps"), list):
                continue
            collected.extend(
                (path, str(job_name), mapping(step, subject=f"{path} {job_name} step"))
                for step in job["steps"]
            )
    return collected


def workflow_uses() -> list[tuple[str, str]]:
    """Return every action reference and revision across the workflows.

    Returns
    -------
    list[tuple[str, str]]
        Each `uses:` value split into its action path and its revision.
    """
    references: list[tuple[str, str]] = []
    for path in workflow_paths():
        text = path.read_text(encoding="utf-8")
        references.extend(re.findall(r"uses:\s*(\S+?)@(\S+)", text))
    return references
