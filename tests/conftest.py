"""Root pytest configuration: plugin registration and cross-cutting fixtures."""

import asyncio
import concurrent.futures as cf
import dataclasses as dc
import os
import threading
import typing as typ

import pytest

import episodic.concurrent_interpreters as ci

# psycopg-binary currently segfaults against py-pglite in this test harness.
os.environ.setdefault("PSYCOPG_IMPL", "python")

if typ.TYPE_CHECKING:
    import collections.abc as cabc
    import contextlib
    import datetime as dt
    import uuid

    import sqlalchemy as sa

    from episodic.canonical.domain import EpisodeTemplate
    from episodic.canonical.unit_of_work_protocols import CanonicalUnitOfWork
    from episodic.worker import (
        CpuDiagnosticRequest,
        CpuDiagnosticResult,
        IoDiagnosticRequest,
        IoDiagnosticResult,
    )
pytest_plugins: list[str] = [
    "tests.fixtures.database",
    "tests.fixtures.llm",
    "tests.fixtures.api",
    "tests.fixtures.ingestion",
    "tests.fixtures.binding",
]


@dc.dataclass(slots=True)
class FakeIoDiagnostic:
    """Record an I/O-bound diagnostic request and return a canned response."""

    seen_messages: list[str]

    def __call__(self, request: IoDiagnosticRequest) -> IoDiagnosticResult:
        """Record the request and return a diagnostic I/O result payload."""
        from episodic.worker import IoDiagnosticResult

        self.seen_messages.append(request.message)
        return IoDiagnosticResult(
            message=request.message,
            correlation_id=request.correlation_id,
            worker_kind="io-bound",
        )


@dc.dataclass(slots=True)
class FakeCpuDiagnostic:
    """Record a CPU-bound diagnostic request and return a canned response."""

    seen_iterations: list[int]

    def __call__(self, request: CpuDiagnosticRequest) -> CpuDiagnosticResult:
        """Record the request and return a diagnostic CPU result payload."""
        from episodic.worker import CpuDiagnosticResult

        self.seen_iterations.append(request.iterations)
        return CpuDiagnosticResult(
            digest=f"digest-{request.iterations}",
            iterations=request.iterations,
            worker_kind="cpu-bound",
        )


def double_worker_value(value: int) -> int:
    """Double an integer for worker fan-out tests."""
    return value * 2


def square_executor_value(value: int) -> int:
    """Return the square of a generated executor input."""
    return value * value


class BlockingMapExecutor(cf.Executor):
    """Executor test double that exposes map/shutdown ordering."""

    def __init__(self) -> None:
        self.map_started = threading.Event()
        self.release_map = threading.Event()
        self.shutdown_called = threading.Event()

    def map(
        self,
        fn: cabc.Callable[..., int],
        *iterables: cabc.Iterable[typ.Any],
        **kwargs: object,
    ) -> cabc.Iterator[int]:
        """Block mapped work until the test releases it."""
        del kwargs
        items = tuple(typ.cast("cabc.Iterable[int]", iterables[0]))
        self.map_started.set()
        if not self.release_map.wait(timeout=5):
            msg = "Timed out waiting for test to release executor.map()."
            raise TimeoutError(msg)
        return iter(fn(item) for item in items)

    def shutdown(
        self,
        wait: bool = True,  # noqa: FBT001, FBT002
        *,
        cancel_futures: bool = False,
    ) -> None:
        """Record that shutdown reached the underlying executor."""
        del wait, cancel_futures
        self.shutdown_called.set()


async def cpu_task_inner_fan_out(items: tuple[int, ...]) -> list[int]:
    """Mirror the documented CPU task interpreter-pool integration pattern."""
    executor = ci.build_cpu_task_executor_from_environment(os.environ)
    try:
        return await executor.map_ordered(double_worker_value, items)
    finally:
        shutdown = getattr(executor, "shutdown", None)
        if shutdown is not None:
            shutdown()


@pytest.fixture
def runtime_environ() -> dict[str, str]:
    """Return the minimal eager Celery worker environment for tests."""
    return {
        "EPISODIC_CELERY_BROKER_URL": "amqp://guest:guest@localhost:5672//",
        "EPISODIC_CELERY_ALWAYS_EAGER": "true",
    }


@pytest.fixture
def captured_interpreter_pool_workers(
    monkeypatch: pytest.MonkeyPatch,
) -> list[int | None]:
    """Enable interpreter-pool dispatch and record requested worker counts."""
    captured_max_workers: list[int | None] = []

    def fake_create_interpreter_pool_executor(max_workers: int | None) -> cf.Executor:
        captured_max_workers.append(max_workers)
        return cf.ThreadPoolExecutor(max_workers=max_workers)

    monkeypatch.setenv("EPISODIC_USE_INTERPRETER_POOL", "1")
    monkeypatch.setenv("EPISODIC_INTERPRETER_POOL_MAX_WORKERS", "2")
    monkeypatch.setattr(ci, "interpreter_pool_supported", lambda: True)
    monkeypatch.setattr(
        ci,
        "_create_interpreter_pool_executor",
        fake_create_interpreter_pool_executor,
    )
    return captured_max_workers


@pytest.fixture
def _function_scoped_runner() -> cabc.Iterator[asyncio.Runner]:
    """Provide a function-scoped asyncio.Runner for sync BDD steps."""
    with asyncio.Runner() as runner:
        yield runner


def temporary_drift_table() -> contextlib.AbstractContextManager[sa.Table]:
    """Compatibility wrapper for tests importing this helper from conftest."""
    from tests.fixtures.database import temporary_drift_table as _temporary_drift_table

    return _temporary_drift_table()


async def create_episode_template_for_binding_tests(
    uow: CanonicalUnitOfWork,
    series_id: uuid.UUID,
    now: dt.datetime,
) -> EpisodeTemplate:
    """Compatibility wrapper for tests importing this helper from conftest."""
    from tests.fixtures.binding import (
        create_episode_template_for_binding_tests as _create_episode_template,
    )

    return await _create_episode_template(uow, series_id, now)
