"""Regression coverage for runtime-evaluated unit-of-work annotations."""

import datetime as dt
import typing as typ
import uuid
from unittest import mock

import pytest

from episodic.canonical.storage import SqlAlchemyUnitOfWork, UnitOfWorkRuntime
from episodic.canonical.storage.generation_run_storage_runtime import (
    GenerationRunStorageRuntime,
)
from episodic.observability import NoopMetrics, NoopTracer, PerfCounterClock

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def test_unit_of_work_supports_autospec_creation() -> None:
    """Autospeccing the unit of work must evaluate its annotations.

    ``mock.create_autospec`` calls ``inspect.signature``, which evaluates
    the ``__init__`` and ``__aexit__`` annotations at runtime. Those
    annotations reference ``collections.abc`` and ``types.TracebackType``,
    so this test fails with ``NameError`` if the imports move back behind
    ``typing.TYPE_CHECKING``.
    """
    specced = mock.create_autospec(SqlAlchemyUnitOfWork, instance=True)

    assert specced is not None, "expected an autospecced unit of work"
    assert isinstance(specced.__aenter__, mock.AsyncMock), (
        "the autospecced unit of work must expose an awaitable __aenter__"
    )
    assert isinstance(specced.__aexit__, mock.AsyncMock), (
        "the autospecced unit of work must expose an awaitable __aexit__"
    )


def _deterministic_unit_of_work_runtime() -> UnitOfWorkRuntime:
    """Build stable collaborators for adapter-forwarding assertions."""
    return UnitOfWorkRuntime(
        metrics=NoopMetrics(),
        monotonic_clock=PerfCounterClock(),
        tracer=NoopTracer(),
        generation_run_runtime=GenerationRunStorageRuntime(
            clock=lambda: dt.datetime(2026, 10, 9, tzinfo=dt.UTC),
            uuid_factory=lambda: uuid.UUID("00000000-0000-0000-0000-000000000099"),
        ),
    )


@pytest.mark.asyncio
async def test_unit_of_work_runtime_reaches_storage_adapters(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Forward the supplied runtime ports unchanged to UoW-owned adapters."""
    from episodic.canonical.storage import uow as uow_module

    runtime = _deterministic_unit_of_work_runtime()
    unit_of_work = SqlAlchemyUnitOfWork(session_factory, runtime=runtime)

    with (
        mock.patch.object(
            uow_module,
            "source_intake_storage_runtime",
            wraps=uow_module.source_intake_storage_runtime,
        ) as source_intake_runtime_factory,
        mock.patch.object(
            uow_module,
            "SqlAlchemyGenerationRunStore",
            autospec=True,
        ) as generation_run_store,
        mock.patch.object(
            uow_module,
            "SqlAlchemyCostLedgerStore",
            autospec=True,
        ),
        mock.patch.object(
            uow_module,
            "SqlAlchemyPricingSnapshotStore",
            autospec=True,
        ) as pricing_snapshot_store,
        mock.patch.object(
            uow_module,
            "InstrumentedPricingSnapshotRepository",
            autospec=True,
        ) as pricing_snapshot_repository,
        mock.patch.object(
            uow_module,
            "SqlAlchemyWorkflowCheckpointStore",
            autospec=True,
        ) as workflow_checkpoint_store,
    ):
        async with unit_of_work:
            source_runtime_kwargs = source_intake_runtime_factory.call_args.kwargs
            assert source_runtime_kwargs["metrics"] is runtime.metrics, (
                "source-intake storage must receive the supplied metrics sink"
            )
            assert (
                source_runtime_kwargs["monotonic_clock"] is runtime.monotonic_clock
            ), "source-intake storage must receive the supplied monotonic clock"

            assert (
                generation_run_store.call_args.kwargs["runtime"]
                is runtime.generation_run_runtime
            ), "generation-run storage must receive the supplied runtime"
            assert pricing_snapshot_store.call_args.kwargs == {}, (
                "the store itself must stay free of telemetry sinks"
            )
            pricing_snapshot_kwargs = pricing_snapshot_repository.call_args.kwargs
            assert pricing_snapshot_kwargs["metrics"] is runtime.metrics, (
                "pricing-snapshot telemetry must receive the supplied metrics sink"
            )
            assert pricing_snapshot_kwargs["tracer"] is runtime.tracer, (
                "pricing-snapshot telemetry must receive the supplied tracer"
            )
            assert pricing_snapshot_kwargs["clock"] is runtime.monotonic_clock, (
                "pricing-snapshot telemetry must receive the supplied monotonic clock"
            )
            assert pricing_snapshot_repository.call_args.args == (
                pricing_snapshot_store.return_value,
            ), "the instrumented repository must wrap the session-bound store"

            workflow_checkpoint_kwargs = workflow_checkpoint_store.call_args.kwargs
            assert workflow_checkpoint_kwargs["metrics"] is runtime.metrics, (
                "workflow checkpoints must receive the supplied metrics sink"
            )
            assert workflow_checkpoint_kwargs["clock"] is runtime.monotonic_clock, (
                "workflow checkpoints must receive the supplied monotonic clock"
            )
