"""Harness for driving the CLI against the real Falcon application.

The CLI talks HTTP and knows nothing about the database, so the scenarios run
the genuine command against the genuine app: an ``httpx.MockTransport``
forwards each request to the ASGI application in-process. The command itself
runs in a worker thread, because its HTTP client is synchronous, while the
ASGI request is served by the scenario's own event loop so it shares the loop
and connection pool the seeding steps used.
"""

import asyncio
import contextlib
import dataclasses as dc
import io
import json
import os
import typing as typ
from unittest import mock

import httpx

from episodic.cli import main
from tests.fixtures.api import api_async_client
from tests.steps.qa_artefact_retrieval_seed import (
    PRINCIPAL_A,
    PRINCIPAL_B,
    require,
)
from tests.steps.qa_artefact_retrieval_support import QaRetrievalContext

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from episodic.api.dependencies import ApiDependencies
    from tests.steps.qa_artefact_retrieval_seed import QaEpisodeFixture

OWNER_TOKEN = PRINCIPAL_A["Authorization"].removeprefix("Bearer ")
FOREIGN_TOKEN = PRINCIPAL_B["Authorization"].removeprefix("Bearer ")

# Empty values count as unset, so this neutralises an operator's own settings
# without depending on the environment in which the suite runs.
_NEUTRAL_ENVIRONMENT = {"EPISODIC_API_URL": "", "EPISODIC_API_TOKEN": ""}


@dc.dataclass(slots=True)
class QaCliContext:
    """Hold one CLI scenario's fixtures and observations.

    Attributes
    ----------
    retrieval : QaRetrievalContext
        Episode, evaluation, and database fixtures shared with the REST
        scenarios.
    exit_code : int | None
        Exit code of the most recent CLI invocation.
    stdout : str
        Standard output captured from that invocation.
    stderr : str
        Standard error captured from that invocation.
    """

    retrieval: QaRetrievalContext
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""

    @property
    def episode(self) -> QaEpisodeFixture:
        """The Background episode the scenario seeded."""
        return require(self.retrieval.episode, "canonical episode")


def build_cli_context(
    session_factory: async_sessionmaker[AsyncSession],
    runner: asyncio.Runner,
) -> QaCliContext:
    """Build a CLI context around the shared retrieval fixtures."""
    return QaCliContext(
        retrieval=QaRetrievalContext(
            session_factory=session_factory,
            runner=runner,
        )
    )


def bridge_transport(
    dependencies: ApiDependencies,
    loop: asyncio.AbstractEventLoop,
) -> httpx.BaseTransport:
    """Return a transport that serves requests through the ASGI application."""

    async def send(request: httpx.Request) -> httpx.Response:
        async with api_async_client(dependencies) as client:
            response = await client.request(
                request.method,
                request.url.path,
                params=dict(request.url.params),
                headers=dict(request.headers),
                content=request.content,
            )
            # The synchronous client asserts on a sync byte stream, so read the
            # body here and hand back a response built from it.
            return httpx.Response(
                response.status_code,
                headers=response.headers,
                content=await response.aread(),
            )

    def handle(request: httpx.Request) -> httpx.Response:
        future = asyncio.run_coroutine_threadsafe(send(request), loop)
        return future.result(timeout=30)

    return httpx.MockTransport(handle)


def _invoke(argv: list[str], transport: httpx.BaseTransport) -> tuple[int, str, str]:
    """Run the CLI with captured output in the calling thread."""
    stdout, stderr = io.StringIO(), io.StringIO()
    with (
        contextlib.redirect_stdout(stdout),
        contextlib.redirect_stderr(stderr),
    ):
        exit_code = main(argv, transport=transport)
    return exit_code, stdout.getvalue(), stderr.getvalue()


def _neutralised_environment() -> contextlib.AbstractContextManager[None]:
    """Return a context manager that clears the operator's API settings."""
    return mock.patch.dict(os.environ, _NEUTRAL_ENVIRONMENT)


@dc.dataclass(frozen=True, slots=True)
class ListOptions:
    """Options for one ``qa evaluations list`` invocation.

    Attributes
    ----------
    token : str | None
        Bearer credential to pass explicitly. ``None`` supplies no token, which
        also suppresses the environment fallback the CLI would otherwise use.
    evaluator : str | None
        Evaluator to filter on, or ``None`` for no filter.
    compliance_status : str | None
        Compliance status to filter on, or ``None`` for no filter.
    output_format : str
        ``"table"`` (the CLI default) or ``"json"``.
    """

    token: str | None = OWNER_TOKEN
    evaluator: str | None = None
    compliance_status: str | None = None
    output_format: str = "table"


def list_evaluations(context: QaCliContext, options: ListOptions) -> None:
    """Invoke ``qa evaluations list`` for the Background episode."""
    dependencies = require(context.retrieval.dependencies, "API dependencies")
    argv = ["qa", "evaluations", "list", str(context.episode.episode_id)]
    if options.token is not None:
        argv.extend(["--token", options.token])
    if options.evaluator is not None:
        argv.extend(["--evaluator", options.evaluator])
    if options.compliance_status is not None:
        argv.extend(["--compliance-status", options.compliance_status])
    if options.output_format != "table":
        argv.extend(["--format", options.output_format])

    async def drive() -> tuple[int, str, str]:
        loop = asyncio.get_running_loop()
        return await asyncio.to_thread(
            _invoke,
            argv,
            bridge_transport(dependencies, loop),
        )

    with _neutralised_environment():
        exit_code, stdout, stderr = context.retrieval.runner.run(drive())
    context.exit_code = exit_code
    context.stdout = stdout
    context.stderr = stderr


def table_rows(context: QaCliContext) -> list[list[str]]:
    """Return the table's data rows, one token list per evaluation."""
    lines = _table_lines(context)
    assert lines[0].startswith("EVALUATOR"), lines[0]
    return [line.split() for line in lines[1:] if not line.endswith("evaluations")]


def table_summary(context: QaCliContext) -> str:
    """Return the summary line beneath the table."""
    return _table_lines(context)[-1]


def _table_lines(context: QaCliContext) -> list[str]:
    """Return the printed table's non-empty lines."""
    lines = [line for line in context.stdout.splitlines() if line.strip()]
    assert lines, f"the CLI printed nothing; stderr was {context.stderr!r}"
    return lines


def json_payload(context: QaCliContext) -> dict[str, object]:
    """Return the printed JSON envelope."""
    return typ.cast("dict[str, object]", json.loads(context.stdout))


def json_items(context: QaCliContext) -> list[dict[str, object]]:
    """Return the evaluations carried by the printed JSON envelope."""
    payload = json_payload(context)
    return typ.cast("list[dict[str, object]]", payload["items"])
