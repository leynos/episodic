"""Falcon resources for polling generation-run state and events."""

import typing as typ

import falcon

from episodic.api.errors import validation_error
from episodic.api.helpers import parse_uuid
from episodic.api.resources.generation_runs_errors import _RETRY_AFTER, _run_not_found
from episodic.api.serializers import (
    serialize_generation_event,
    serialize_generation_run,
)
from episodic.api.source_idempotency import principal_id
from episodic.canonical.generation_run_errors import RunNotFound
from episodic.canonical.generation_run_ports import event_seq
from episodic.observability import NoopTracer

if typ.TYPE_CHECKING:
    from episodic.api.types import UowFactory
    from episodic.observability import TracerPort

_MAX_EVENT_LIMIT = 100
_DEFAULT_EVENT_LIMIT = 20


class GenerationRunResource:
    """Return one generation-run polling snapshot."""

    def __init__(
        self, uow_factory: UowFactory, *, tracer: TracerPort | None = None
    ) -> None:
        self._uow_factory = uow_factory
        self._tracer = NoopTracer() if tracer is None else tracer

    async def on_get(
        self,
        req: falcon.Request,
        resp: falcon.Response,
        run_id: str,
    ) -> None:
        """Return the current generation-run state."""
        with self._tracer.start_span(
            "generation_run.read",
            attributes={"operation": "generation_run.read"},
        ) as span:
            try:
                parsed_run_id = parse_uuid(run_id, "run_id")
            except falcon.HTTPError:
                span.set_attribute("outcome", "rejected")
                span.set_attribute("failure_category", "invalid_input")
                raise
            actor = principal_id(req)
            if actor is None:
                span.set_attribute("outcome", "not_found")
                span.set_attribute("failure_category", "run.not_found")
                raise _run_not_found(parsed_run_id)
            async with self._uow_factory() as uow:
                run = await uow.generation_runs.get_run(parsed_run_id)
            if run is None:
                span.set_attribute("outcome", "not_found")
                span.set_attribute("failure_category", "run.not_found")
                raise _run_not_found(parsed_run_id)
            if run.actor != actor:
                span.set_attribute("outcome", "not_found")
                span.set_attribute("failure_category", "run.not_found")
                raise _run_not_found(parsed_run_id)
            resp.media = serialize_generation_run(run)
            resp.status = falcon.HTTP_200
            if not run.status.is_terminal():
                resp.set_header("Retry-After", _RETRY_AFTER)
            span.set_attribute("outcome", "success")


class GenerationRunEventsResource:
    """Return cursor-paginated events for one generation run."""

    def __init__(
        self, uow_factory: UowFactory, *, tracer: TracerPort | None = None
    ) -> None:
        self._uow_factory = uow_factory
        self._tracer = NoopTracer() if tracer is None else tracer

    async def on_get(
        self,
        req: falcon.Request,
        resp: falcon.Response,
        run_id: str,
    ) -> None:
        """List events after an optional sequence cursor."""
        with self._tracer.start_span(
            "generation_run.events.list",
            attributes={"operation": "generation_run.events.list"},
        ) as span:
            try:
                parsed_run_id = parse_uuid(run_id, "run_id")
                after_seq = _parse_optional_positive_int(req, "after_seq")
                limit = _parse_limit(req)
                offset = _parse_offset(req)
                if after_seq is not None and offset != 0:
                    message = "after_seq and offset cannot be combined."
                    raise validation_error(
                        message,
                        field="offset",
                        constraint="exclusive_with_after_seq",
                    )
            except falcon.HTTPError:
                span.set_attribute("outcome", "rejected")
                span.set_attribute("failure_category", "invalid_input")
                raise
            span.set_attribute(
                "pagination", "cursor" if after_seq is not None else "offset"
            )
            actor = principal_id(req)
            if actor is None:
                span.set_attribute("outcome", "not_found")
                span.set_attribute("failure_category", "run.not_found")
                raise _run_not_found(parsed_run_id)
            async with self._uow_factory() as uow:
                run = await uow.generation_runs.get_run(parsed_run_id)
                if run is None or run.actor != actor:
                    span.set_attribute("outcome", "not_found")
                    span.set_attribute("failure_category", "run.not_found")
                    raise _run_not_found(parsed_run_id)
                try:
                    events = await uow.generation_runs.list_events(
                        parsed_run_id,
                        after_seq=None if after_seq is None else event_seq(after_seq),
                        limit=limit,
                        offset=offset,
                    )
                    total = await uow.generation_runs.count_events(
                        parsed_run_id,
                        after_seq=None if after_seq is None else event_seq(after_seq),
                    )
                except RunNotFound as exc:
                    span.set_attribute("outcome", "not_found")
                    span.set_attribute("failure_category", "run.not_found")
                    raise _run_not_found(parsed_run_id) from exc
            resp.media = {
                "items": [serialize_generation_event(event) for event in events],
                "after_seq": after_seq,
                "limit": limit,
                "offset": offset,
                "total": total,
            }
            resp.status = falcon.HTTP_200
            span.set_attribute("outcome", "success")


def _parse_optional_positive_int(req: falcon.Request, name: str) -> int | None:
    raw = req.get_param(name)
    if raw is None:
        return None
    value = _parse_int(raw, name)
    if value < 1:
        message = f"{name} must be a positive integer."
        raise validation_error(
            message,
            field=name,
            constraint="range",
        )
    return value


def _parse_limit(req: falcon.Request) -> int:
    raw = req.get_param("limit")
    value = _DEFAULT_EVENT_LIMIT if raw is None else _parse_int(raw, "limit")
    if value < 1 or value > _MAX_EVENT_LIMIT:
        message = f"limit must be between 1 and {_MAX_EVENT_LIMIT}."
        raise validation_error(
            message,
            field="limit",
            constraint="range",
        )
    return value


def _parse_offset(req: falcon.Request) -> int:
    """Parse the event collection offset."""
    raw = req.get_param("offset")
    value = 0 if raw is None else _parse_int(raw, "offset")
    if value < 0:
        message = "offset must be a non-negative integer."
        raise validation_error(
            message,
            field="offset",
            constraint="range",
        )
    return value


def _parse_int(raw: str, name: str) -> int:
    try:
        return int(raw)
    except ValueError as exc:
        message = f"{name} must be an integer."
        raise validation_error(
            message,
            field=name,
            constraint="type",
        ) from exc
