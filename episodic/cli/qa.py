"""The ``qa evaluations list`` command.

The command is a thin composition: build the query, let
:class:`~episodic.cli.client.QaApiClient` fetch the page, and hand the decoded
payload to a pure renderer. It therefore returns the text to print rather than
printing it, which keeps standard output owned by :mod:`episodic.cli`.
"""

import typing as typ
import uuid  # ruff: ignore[typing-only-standard-library-import]  # cyclopts resolves command annotations when registering.

import cyclopts

from episodic.canonical.qa_artefacts import QaComplianceStatus, QaEvaluator
from episodic.cli.client import CliRuntime, QaApiClient, QaEvaluationQuery
from episodic.cli.rendering import render_json, render_table

type OutputFormat = typ.Literal["table", "json"]

# The wire values, not cyclopts' kebab-cased enum names, are the documented
# choices, so each filter states them explicitly.
_EVALUATOR_CHOICES = tuple(member.value for member in QaEvaluator)
_COMPLIANCE_CHOICES = tuple(member.value for member in QaComplianceStatus)


def register(parent: cyclopts.App, runtime: CliRuntime) -> None:
    """Attach the ``qa`` command group to ``parent``.

    Parameters
    ----------
    parent : cyclopts.App
        Root application the group is registered on.
    runtime : CliRuntime
        State the meta launcher fills before this group's command runs.
    """
    qa_app = cyclopts.App(name="qa", help="Inspect recorded QA artefacts.")
    evaluations_app = cyclopts.App(
        name="evaluations",
        help="Inspect the QA evaluations recorded for an episode.",
    )

    @evaluations_app.command(name="list")
    # pylint: disable-next=too-many-arguments  # Every parameter is a documented CLI option.
    def list_evaluations(  # ruff: ignore[too-many-arguments]  # Every parameter is a documented CLI option.
        episode: typ.Annotated[
            uuid.UUID,
            cyclopts.Parameter(help="Identifier of the episode to inspect."),
        ],
        *,
        evaluator: typ.Annotated[
            QaEvaluator | None,
            cyclopts.Parameter(
                choices=_EVALUATOR_CHOICES,
                help="Only report this evaluator's artefacts.",
            ),
        ] = None,
        compliance_status: typ.Annotated[
            QaComplianceStatus | None,
            cyclopts.Parameter(
                choices=_COMPLIANCE_CHOICES,
                help="Only report this compliance status.",
            ),
        ] = None,
        limit: typ.Annotated[
            int | None,
            cyclopts.Parameter(help="Maximum number of evaluations to list."),
        ] = None,
        offset: typ.Annotated[
            int | None,
            cyclopts.Parameter(help="Number of evaluations to skip."),
        ] = None,
        output_format: typ.Annotated[
            OutputFormat,
            cyclopts.Parameter(name="--format", help="Output format."),
        ] = "table",
    ) -> str:
        """List the QA evaluations recorded for an episode.

        Parameters
        ----------
        episode : uuid.UUID
            Episode whose evaluations are requested.
        evaluator : QaEvaluator | None
            Optional evaluator filter.
        compliance_status : QaComplianceStatus | None
            Optional compliance-status filter.
        limit : int | None
            Optional page size.
        offset : int | None
            Optional page offset.
        output_format : {"table", "json"}
            Rendering to produce. ``json`` prints the API envelope verbatim.

        Returns
        -------
        str
            The rendered page, ready for standard output.

        Raises
        ------
        CliError
            If the API could not be reached or answered with an error.
        """  # ruff: ignore[docstring-extraneous-exception]  # QaApiClient raises it from this call.
        query = QaEvaluationQuery(
            episode_id=episode,
            evaluator=evaluator,
            compliance_status=compliance_status,
            limit=limit,
            offset=offset,
        )
        page = QaApiClient(runtime).list_evaluations(query)
        return render_json(page) if output_format == "json" else render_table(page)

    qa_app.command(evaluations_app)
    parent.command(qa_app)
