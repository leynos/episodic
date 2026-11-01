"""HTTP helpers for QA-artefact retrieval BDD scenarios and API tests.

The episode and evaluation fixtures live in
:mod:`tests.steps.qa_artefact_retrieval_seed`; this module owns the per-scenario
state, the authenticated ASGI client, and the request wrappers that the
behavioural steps call synchronously.
"""

import dataclasses as dc
import typing as typ
import uuid

from sqlalchemy import update

from episodic.canonical.qa_artefacts import (
    MAX_CODE_CHARS,
    QA_ARTEFACT_SCHEMA_VERSION,
)
from episodic.canonical.storage.qa_artefact_models import (
    QaEvaluationRecord,
    QaFindingRecord,
)
from tests.fixtures.api import api_async_client, build_api_dependencies
from tests.fixtures.generation_run_api import (
    HeaderPrincipalAuthorization,
    RecordingLauncher,
)
from tests.steps.qa_artefact_retrieval_seed import (
    PRINCIPAL_A,
    QaEpisodeFixture,
    create_generated_episode,
    record_anthem_failure,
    record_anthem_success,
    record_background_evaluations,
    record_chrono_evaluation,
    record_pedante_evaluation,
    require,
)

if typ.TYPE_CHECKING:
    import asyncio
    import collections.abc as cabc

    import httpx
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from episodic.api.dependencies import ApiDependencies


@dc.dataclass(slots=True)
class QaRetrievalContext:
    """Hold infrastructure and observations for one behavioural scenario.

    Attributes
    ----------
    session_factory : async_sessionmaker[AsyncSession]
        Session factory backing the scenario's database.
    runner : asyncio.Runner
        Runner that owns every asynchronous call the steps make.
    dependencies : ApiDependencies | None
        Application dependencies, built when the scenario's episode is set up.
    episode : QaEpisodeFixture | None
        Episode seeded by the Background.
    pedante_evaluation_id : uuid.UUID | None
        Identifier of the recorded Pedante evaluation.
    listed : dict[str, object] | None
        Last successful list response body.
    details : dict[str, dict[str, object]]
        Detail response bodies keyed by evaluation identifier.
    status_code : int | None
        Status of the most recent list or detail request.
    error_payload : dict[str, object] | None
        Error envelope of the most recent failed request.
    """

    session_factory: async_sessionmaker[AsyncSession]
    runner: asyncio.Runner
    dependencies: ApiDependencies | None = None
    episode: QaEpisodeFixture | None = None
    pedante_evaluation_id: uuid.UUID | None = None
    listed: dict[str, object] | None = None
    details: dict[str, dict[str, object]] = dc.field(default_factory=dict)
    status_code: int | None = None
    error_payload: dict[str, object] | None = None

    async def send(
        self,
        path: str,
        *,
        headers: cabc.Mapping[str, str] | None = None,
        params: cabc.Mapping[str, str] | None = None,
    ) -> httpx.Response:
        """Issue one GET request against the scenario's ASGI application."""
        dependencies = require(self.dependencies, "QA retrieval dependencies")
        request_headers = PRINCIPAL_A if headers is None else headers
        async with api_async_client(dependencies) as client:
            return await client.get(path, headers=request_headers, params=params)


def build_qa_dependencies(
    session_factory: async_sessionmaker[AsyncSession],
) -> ApiDependencies:
    """Build API dependencies that authenticate the test principals."""
    return dc.replace(
        build_api_dependencies(
            session_factory,
            authorization=HeaderPrincipalAuthorization(),
        ),
        launcher=RecordingLauncher(),
    )


async def seed_background_evaluations(
    dependencies: ApiDependencies,
) -> QaEpisodeFixture:
    """Create one generated episode and its three background evaluations."""
    episode = await create_generated_episode(dependencies)
    await record_background_evaluations(dependencies, episode)
    return episode


def listing_items(response: httpx.Response) -> list[dict[str, object]]:
    """Return the items of a successful listing response."""
    payload = typ.cast("dict[str, object]", response.json())
    return typ.cast("list[dict[str, object]]", payload["items"])


def error_envelope(response: httpx.Response) -> dict[str, object]:
    """Return an error response's envelope."""
    return typ.cast("dict[str, object]", response.json())


async def pretend_a_newer_release_wrote_the_row(
    session_factory: async_sessionmaker[AsyncSession],
    evaluation_id: str,
) -> None:
    """Raise the stored schema version past what this release reads.

    One finding is also widened past this release's bounds. A reader that
    validated findings before checking the stored version would fail on the
    widened field and answer 500, so the update makes the documented 422 the
    only way through.
    """
    evaluation = uuid.UUID(evaluation_id)
    async with session_factory() as session:
        await session.execute(
            update(QaEvaluationRecord)
            .where(QaEvaluationRecord.id == evaluation)
            .values(artefact_schema_version=QA_ARTEFACT_SCHEMA_VERSION + 1)
        )
        widened = await session.execute(
            update(QaFindingRecord)
            .where(QaFindingRecord.evaluation_id == evaluation)
            .values(code="x" * (MAX_CODE_CHARS + 1))
        )
        await session.commit()
    assert widened.rowcount, "the seeded evaluation carries no findings to widen"


def establish_generated_episode(context: QaRetrievalContext) -> None:
    """Create the Background episode and its generated TEI draft."""
    if context.dependencies is None:
        context.dependencies = build_qa_dependencies(context.session_factory)

    async def _create() -> QaEpisodeFixture:
        dependencies = require(context.dependencies, "QA retrieval dependencies")
        return await create_generated_episode(dependencies)

    context.episode = context.runner.run(_create())


def record_pedante_for_context(context: QaRetrievalContext) -> None:
    """Record the Background Pedante evaluation."""
    dependencies = require(context.dependencies, "QA retrieval dependencies")
    episode = require(context.episode, "canonical episode")

    async def _record_pedante() -> uuid.UUID:
        return await record_pedante_evaluation(dependencies, episode)

    context.pedante_evaluation_id = context.runner.run(_record_pedante())


def record_chrono_for_context(context: QaRetrievalContext) -> None:
    """Record the Background Chrono evaluation."""
    dependencies = require(context.dependencies, "QA retrieval dependencies")
    episode = require(context.episode, "canonical episode")
    context.runner.run(record_chrono_evaluation(dependencies, episode))


def record_anthem_failure_for_context(context: QaRetrievalContext) -> None:
    """Record the Background Anthem failure."""
    dependencies = require(context.dependencies, "QA retrieval dependencies")
    episode = require(context.episode, "canonical episode")
    context.runner.run(record_anthem_failure(dependencies, episode))


def record_anthem_success_for_context(context: QaRetrievalContext) -> None:
    """Record a successful Anthem retry for the Background episode."""
    dependencies = require(context.dependencies, "QA retrieval dependencies")
    episode = require(context.episode, "canonical episode")
    context.runner.run(record_anthem_success(dependencies, episode))


def _store_listing(
    context: QaRetrievalContext,
    response: httpx.Response,
) -> None:
    """Store a list response, separating success payloads from errors."""
    context.status_code = response.status_code
    if response.status_code == 200:
        context.listed = typ.cast("dict[str, object]", response.json())
        context.error_payload = None
    else:
        context.listed = None
        context.error_payload = typ.cast("dict[str, object]", response.json())


def request_evaluations(
    context: QaRetrievalContext,
    *,
    evaluator: str | None = None,
    compliance_status: str | None = None,
    headers: cabc.Mapping[str, str] | None = None,
) -> None:
    """Request the episode's evaluations, optionally filtering them."""
    episode = require(context.episode, "canonical episode")
    params = {
        name: value
        for name, value in (
            ("evaluator", evaluator),
            ("compliance_status", compliance_status),
        )
        if value is not None
    }
    response = context.runner.run(
        context.send(
            f"/v1/episodes/{episode.episode_id}/qa-evaluations",
            headers=headers,
            params=params,
        )
    )
    _store_listing(context, response)


def request_evaluation_detail(
    context: QaRetrievalContext,
    evaluation_id: str,
) -> None:
    """Request one evaluation by identifier and store its detail payload."""
    response = context.runner.run(context.send(f"/v1/qa-evaluations/{evaluation_id}"))
    context.status_code = response.status_code
    if response.status_code == 200:
        context.details[evaluation_id] = typ.cast("dict[str, object]", response.json())
        context.error_payload = None
    else:
        context.error_payload = typ.cast("dict[str, object]", response.json())


def request_listed_details(context: QaRetrievalContext) -> None:
    """Request the detail representation of every listed evaluation."""
    listing = require(context.listed, "evaluation listing")
    items = typ.cast("list[dict[str, object]]", listing["items"])
    for item in items:
        request_evaluation_detail(context, typ.cast("str", item["id"]))


def request_pedante_detail(context: QaRetrievalContext) -> None:
    """Request the recorded Pedante evaluation by identifier."""
    evaluation_id = require(context.pedante_evaluation_id, "Pedante evaluation")
    request_evaluation_detail(context, str(evaluation_id))
