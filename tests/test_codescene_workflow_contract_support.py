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

from tests.workflow_call_graph import local_workflow_name, reachable

REPOSITORY_ROOT = pl.Path(__file__).resolve().parents[1]
WORKFLOWS_DIRECTORY = REPOSITORY_ROOT / ".github" / "workflows"

# A workflow document's keys are not all strings: PyYAML resolves an unquoted
# `on:` key to the boolean True. Its values are arbitrary YAML. Both are
# therefore `object`, and every consumer narrows through `mapping`.
type Mapping = dict[object, object]
type Workflow = Mapping
type Step = Mapping


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
    # `dict` is invariant, so narrowing an `object` gives dict[Unknown, Unknown]
    # rather than the alias. The assertion above is the check the cast stands on.
    return typ.cast("Workflow", value)


class WorkflowReadError(OSError):
    """Raised when a workflow file cannot be read or parsed, naming the file.

    A contract several frames away would otherwise fail with an opaque decoding
    or YAML error naming no workflow.
    """


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

    Raises
    ------
    WorkflowReadError
        If the file cannot be read, does not decode, or is not YAML.
    """
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as error:
        message = f"{path} could not be read as a workflow: {error}"
        raise WorkflowReadError(message) from error
    return mapping(document, subject=str(path))


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
        if not isinstance(value, dict) or event not in value:
            continue
        triggers = typ.cast("Workflow", value)
        configuration = triggers[event]
        if not isinstance(configuration, dict):
            return None
        return typ.cast("Workflow", configuration)
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
            if not isinstance(job, dict):
                continue
            steps = typ.cast("Workflow", job).get("steps")
            if not isinstance(steps, list):
                continue
            collected.extend(
                (path, str(job_name), mapping(step, subject=f"{path} {job_name} step"))
                for step in typ.cast("list[object]", steps)
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


def local_workflow_calls(path: pl.Path) -> frozenset[str]:
    """Return the file names of the same-repository workflows one workflow calls.

    A call is local when :func:`workflow_call_graph.local_workflow_name` reads
    it so; a call to another repository is not followed, because its content
    is not in this tree.

    Parameters
    ----------
    path : pl.Path
        Workflow document to read.

    Returns
    -------
    frozenset[str]
        Called workflow file names, whether or not such a file exists.
    """
    names = (
        local_workflow_name(typ.cast("Workflow", job).get("uses"))
        for job in workflow_jobs(path).values()
        if isinstance(job, dict)
    )
    return frozenset(name for name in names if name is not None)


def workflows_reachable_from(events: frozenset[str]) -> frozenset[pl.Path]:
    """Return every workflow one of the given events can reach.

    A workflow that declares only ``workflow_call`` still runs on a pull
    request when a pull-request workflow calls it, and it receives inherited
    secrets, so a contract that enumerates triggers alone cannot see it. This
    reads the repository into a call graph; :func:`workflow_call_graph.reachable`
    closes it.

    Parameters
    ----------
    events : frozenset[str]
        Trigger names that start the traversal.

    Returns
    -------
    frozenset[pl.Path]
        The entry workflows and everything they call, transitively. A local
        call to a workflow the repository does not hold propagates
        ``UnresolvedWorkflowCallError``; an unreadable workflow propagates
        :class:`WorkflowReadError`.
    """
    paths = workflow_paths()
    calls = {path.name: local_workflow_calls(path) for path in paths}
    entries = [path.name for path in paths if workflow_triggers(path) & events]
    return frozenset(WORKFLOWS_DIRECTORY / name for name in reachable(calls, entries))
