"""Falcon resources for QA-artefact retrieval endpoints.

Both resources resolve the evaluation's episode and require its launcher run to
belong to the requesting principal. An artefact owned by someone else is
reported as absent rather than forbidden, so the response cannot confirm that
it exists.
"""

import typing as typ

import falcon

from episodic.api.episode_access import read_owned_episode
from episodic.api.errors import http_error
from episodic.api.helpers import parse_enum_param, parse_pagination, parse_uuid
from episodic.api.serializers import (
    serialize_qa_evaluation,
    serialize_qa_evaluation_summary,
)
from episodic.api.source_idempotency import principal_id
from episodic.canonical.qa_artefact_errors import UnsupportedQaArtefactSchemaError
from episodic.canonical.qa_artefact_ports import QaEvaluationListRequest
from episodic.canonical.qa_artefact_service import (
    get_qa_evaluation,
    list_qa_evaluations,
)
from episodic.canonical.qa_artefacts import QaComplianceStatus, QaEvaluator
from episodic.observability import NoopTracer

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from episodic.api.types import UowFactory
    from episodic.observability import SpanHandle, TracerPort


def _evaluation_not_found(
    details: cabc.Mapping[str, object],
) -> falcon.HTTPNotFound:
    """Build the not-found error shared by both retrieval endpoints."""
    return typ.cast(
        "falcon.HTTPNotFound",
        http_error(
            falcon.HTTPNotFound(description="QA evaluation not found."),
            code="qa_evaluation_not_found",
            details=dict(details),
        ),
    )


def _record_rejection(span: SpanHandle, failure_category: str) -> None:
    """Mark the span as a rejected request with its stable category."""
    span.set_attribute("outcome", "rejected")
    span.set_attribute("failure_category", failure_category)


def _record_not_found(span: SpanHandle, failure_category: str) -> None:
    """Mark the span as a not-found response with its stable category."""
    span.set_attribute("outcome", "not_found")
    span.set_attribute("failure_category", failure_category)


def _unsupported_schema(
    error: UnsupportedQaArtefactSchemaError,
) -> falcon.HTTPUnprocessableEntity:
    """Build the response for a row written by a newer release."""
    return typ.cast(
        "falcon.HTTPUnprocessableEntity",
        http_error(
            falcon.HTTPUnprocessableEntity(
                description=(
                    "The QA artefact was recorded with a schema this release "
                    "cannot read."
                ),
            ),
            code="qa_artefact_schema_unsupported",
            details={
                "evaluation_id": str(error.evaluation_id),
                "artefact_schema_version": error.stored_version,
                "supported_artefact_schema_version": error.supported_version,
            },
        ),
    )


class EpisodeQaEvaluationsResource:
    """List one episode's QA evaluations, filtered and paginated.

    Parameters
    ----------
    uow_factory : UowFactory
        Callable dependency invoked to construct a unit of work per request.
    tracer : TracerPort | None, optional
        Span recorder. A no-op tracer is used when omitted.
    """

    def __init__(
        self,
        uow_factory: UowFactory,
        *,
        tracer: TracerPort | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._tracer = NoopTracer() if tracer is None else tracer

    async def on_get(
        self,
        req: falcon.Request,
        resp: falcon.Response,
        episode_id: str,
    ) -> None:
        """Return one page of the episode's QA evaluations.

        Parameters
        ----------
        req : falcon.Request
            Request carrying the optional evaluator and compliance-status
            filters and the pagination.
        resp : falcon.Response
            Response populated with the page envelope.
        episode_id : str
            Episode UUID from the route path.

        Raises
        ------
        falcon.HTTPBadRequest
            If the episode identifier, a filter value, or the pagination is
            invalid.
        falcon.HTTPNotFound
            If the episode is absent or its launcher run belongs to another
            principal.
        falcon.HTTPUnprocessableEntity
            If a stored row records a payload shape newer than this release
            reads.
        """  # ruff: ignore[docstring-missing-exception, docstring-extraneous-exception]  # The errors come from parse_uuid(), parse_pagination(), parse_enum_param(), _evaluation_not_found(), and _unsupported_schema(), which the docstring describes as one contract.
        with self._tracer.start_span(
            "qa_evaluations.list",
            attributes={"operation": "qa_evaluations.list"},
        ) as span:
            try:
                parsed_episode_id = parse_uuid(episode_id, "episode_id")
                page = parse_pagination(req)
                evaluator = parse_enum_param(req, "evaluator", QaEvaluator)
                compliance_status = parse_enum_param(
                    req,
                    "compliance_status",
                    QaComplianceStatus,
                )
            except falcon.HTTPError:
                _record_rejection(span, "invalid_input")
                raise
            span.set_attribute("pagination", "offset")
            async with self._uow_factory() as uow:
                episode = await read_owned_episode(
                    uow,
                    parsed_episode_id,
                    principal_id(req),
                )
                if episode is None:
                    _record_not_found(span, "episode.not_found")
                    raise _evaluation_not_found({"episode_id": str(parsed_episode_id)})
                try:
                    summaries, total = await list_qa_evaluations(
                        uow,
                        QaEvaluationListRequest(
                            episode_id=parsed_episode_id,
                            pagination=page,
                            evaluator=evaluator,
                            compliance_status=compliance_status,
                        ),
                    )
                except UnsupportedQaArtefactSchemaError as error:
                    # The caller already owns the episode, so naming the schema
                    # failure reveals nothing it could not learn from the rows.
                    _record_rejection(span, "qa_artefact_schema_unsupported")
                    raise _unsupported_schema(error) from error
            resp.media = {
                "items": [
                    serialize_qa_evaluation_summary(summary) for summary in summaries
                ],
                "limit": page.limit,
                "offset": page.offset,
                "total": total,
            }
            resp.status = falcon.HTTP_200
            span.set_attribute("outcome", "success")


class QaEvaluationResource:
    """Return one QA evaluation together with its findings.

    Parameters
    ----------
    uow_factory : UowFactory
        Callable dependency invoked to construct a unit of work per request.
    tracer : TracerPort | None, optional
        Span recorder. A no-op tracer is used when omitted.
    """

    def __init__(
        self,
        uow_factory: UowFactory,
        *,
        tracer: TracerPort | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._tracer = NoopTracer() if tracer is None else tracer

    async def on_get(
        self,
        req: falcon.Request,
        resp: falcon.Response,
        evaluation_id: str,
    ) -> None:
        """Return one evaluation's summary and ordered findings.

        Parameters
        ----------
        req : falcon.Request
            Request identifying the calling principal.
        resp : falcon.Response
            Response populated with the evaluation and its findings.
        evaluation_id : str
            Evaluation UUID from the route path.

        Raises
        ------
        falcon.HTTPBadRequest
            If the evaluation identifier is not a UUID.
        falcon.HTTPNotFound
            If the evaluation is absent or its episode's launcher run belongs
            to another principal.
        falcon.HTTPUnprocessableEntity
            If the stored row records a payload shape newer than this release
            reads, and the caller owns its episode.
        """  # ruff: ignore[docstring-missing-exception, docstring-extraneous-exception]  # parse_uuid(), _evaluation_not_found(), and _unsupported_schema() raise the documented errors.
        with self._tracer.start_span(
            "qa_evaluation.read",
            attributes={"operation": "qa_evaluation.read"},
        ) as span:
            try:
                parsed_evaluation_id = parse_uuid(evaluation_id, "evaluation_id")
            except falcon.HTTPError:
                _record_rejection(span, "invalid_input")
                raise
            details = {"evaluation_id": str(parsed_evaluation_id)}
            async with self._uow_factory() as uow:
                try:
                    evaluation = await get_qa_evaluation(uow, parsed_evaluation_id)
                except UnsupportedQaArtefactSchemaError as error:
                    # The row is unreadable, but its episode still decides
                    # whether this caller may learn that it exists.
                    episode = await read_owned_episode(
                        uow,
                        error.episode_id,
                        principal_id(req),
                    )
                    if episode is None:
                        _record_not_found(span, "evaluation.not_found")
                        raise _evaluation_not_found(details) from error
                    _record_rejection(span, "qa_artefact_schema_unsupported")
                    raise _unsupported_schema(error) from error
                if evaluation is None:
                    _record_not_found(span, "evaluation.not_found")
                    raise _evaluation_not_found(details)
                episode = await read_owned_episode(
                    uow,
                    evaluation.summary_record.episode_id,
                    principal_id(req),
                )
                if episode is None:
                    _record_not_found(span, "evaluation.not_found")
                    raise _evaluation_not_found(details)
            resp.media = serialize_qa_evaluation(evaluation)
            resp.status = falcon.HTTP_200
            span.set_attribute("outcome", "success")
