"""Polling resource for one persisted generation run."""

import typing as typ

import falcon

from episodic.api.helpers import parse_uuid
from episodic.api.serializers import serialize_generation_run
from episodic.api.source_idempotency import principal_id
from episodic.observability import NoopTracer, TracerPort

from .generation_run_errors import run_not_found

_RETRY_AFTER = "1"

if typ.TYPE_CHECKING:
    from episodic.api.resources.base import UowFactory
    from episodic.observability import SpanHandle


class GenerationRunResource:
    """Return one caller-owned generation-run polling snapshot."""

    def __init__(
        self, uow_factory: UowFactory, *, tracer: TracerPort | None = None
    ) -> None:
        self._uow_factory = uow_factory
        self._tracer = NoopTracer() if tracer is None else tracer

    async def on_get(
        self, req: falcon.Request, resp: falcon.Response, run_id: str
    ) -> None:
        """Return the current caller-owned generation-run state."""
        with self._tracer.start_span(
            "generation_run.read", attributes={"operation": "generation_run.read"}
        ) as span:
            try:
                parsed_run_id = parse_uuid(run_id, "run_id")
            except falcon.HTTPError:
                span.set_attribute("outcome", "rejected")
                span.set_attribute("failure_category", "invalid_input")
                raise
            actor = principal_id(req)
            if actor is None:
                _record_not_found(span)
                raise run_not_found(parsed_run_id)
            async with self._uow_factory() as uow:
                run = await uow.generation_runs.get_run(parsed_run_id)
            if run is None or run.actor != actor:
                _record_not_found(span)
                raise run_not_found(parsed_run_id)
            resp.media = serialize_generation_run(run)
            resp.status = falcon.HTTP_200
            if not run.status.is_terminal():
                resp.set_header("Retry-After", _RETRY_AFTER)
            span.set_attribute("outcome", "success")


def _record_not_found(span: SpanHandle) -> None:
    """Annotate a generation-run read span with the non-disclosing result."""
    span.set_attribute("outcome", "not_found")
    span.set_attribute("failure_category", "run.not_found")
