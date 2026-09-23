"""Pure reading of reusable-workflow calls: reference shapes and reachability.

The CodeScene contract's pull-request lane is a closure: the workflows a
pull-request event triggers, and every workflow they call, transitively. This
module owns the two pure halves of that. It reads a ``uses:`` reference to the
workflow file it names, and it closes a call graph over its entries. Neither
touches the filesystem. The support module reads the repository's workflows
into a call graph and hands it here, so each half can be tested on its own:
the shapes by example, and the closure by property against an independent
reference.
"""

import pathlib as pl
import typing as typ

if typ.TYPE_CHECKING:
    import collections.abc as cabc

# Where a same-repository reusable workflow lives. GitHub does not look in its
# subdirectories.
LOCAL_WORKFLOW_DIRECTORY = pl.PurePosixPath(".github/workflows")
# The two prefixes GitHub documents for a same-repository call: the
# workspace-relative `./` and the self-repository `$/`, which GitHub.com
# recommends and which resolves to the running commit without a checkout.
SELF_REPOSITORY_PREFIXES = ("./", "$/")


class UnresolvedWorkflowCallError(LookupError):
    """Raised when a call names a workflow the call graph does not hold.

    The closure cannot vouch for a workflow it never read, so a call it cannot
    resolve fails the reading rather than dropping out of the lane.
    """


def local_workflow_name(reference: object) -> str | None:
    """Return the workflow file a same-repository ``uses:`` reference names.

    The reference is matched by shape: less a leading ``./`` or ``$/``, the two
    same-repository prefixes GitHub documents, it must name a file directly
    under ``.github/workflows/``. Whether that file exists is the reachability
    reading's question, not this one's.

    Parameters
    ----------
    reference : object
        A job's ``uses:`` value.

    Returns
    -------
    str | None
        The workflow's file name, or None when the reference is not a local
        workflow call.

    Examples
    --------
    >>> local_workflow_name("./.github/workflows/ci.yml")
    'ci.yml'
    >>> local_workflow_name("$/.github/workflows/ci.yml")
    'ci.yml'
    >>> local_workflow_name("leynos/episodic/.github/workflows/ci.yml@main") is None
    True
    """
    if not isinstance(reference, str):
        return None
    relative = pl.PurePosixPath(_without_self_repository_prefix(reference))
    return relative.name if relative.parent == LOCAL_WORKFLOW_DIRECTORY else None


def _without_self_repository_prefix(reference: str) -> str:
    """Return a ``uses:`` reference less one leading same-repository prefix."""
    return next(
        (
            reference.removeprefix(prefix)
            for prefix in SELF_REPOSITORY_PREFIXES
            if reference.startswith(prefix)
        ),
        reference,
    )


def reachable(
    calls: cabc.Mapping[str, frozenset[str]], entries: cabc.Iterable[str]
) -> frozenset[str]:
    """Return the entries and every workflow they call, transitively.

    Parameters
    ----------
    calls : Mapping[str, frozenset[str]]
        Each workflow's file name mapped to the local workflows it calls.
    entries : Iterable[str]
        The workflows the traversal starts from.

    Returns
    -------
    frozenset[str]
        Every workflow reached.

    Raises
    ------
    UnresolvedWorkflowCallError
        If an entry or a call names a workflow ``calls`` does not hold.

    Examples
    --------
    >>> graph = {"a": frozenset({"b"}), "b": frozenset(), "c": frozenset()}
    >>> sorted(reachable(graph, ["a"]))
    ['a', 'b']
    """
    pending = list(entries)
    reached: set[str] = set()
    while pending:
        current = pending.pop()
        if current in reached:
            continue
        if current not in calls:
            message = f"{current} is called or named but does not exist"
            raise UnresolvedWorkflowCallError(message)
        reached.add(current)
        pending.extend(calls[current] - reached)
    return frozenset(reached)
