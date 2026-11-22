"""Deterministic evaluator doubles and QA-run fixtures for launcher tests."""

import asyncio
import dataclasses as dc
import typing as typ

from episodic.canonical.generation_graph_ports import (
    EvaluationSubject,
    QualityEvaluation,
)
from episodic.canonical.generation_quality import QaStatus, QualityMode
from episodic.canonical.generation_routing import QualityVerdict
from episodic.canonical.storage import SqlAlchemyUnitOfWork
from tests.generation_run_launcher_support import (
    _prepare_pending_run,
    _run,
)

if typ.TYPE_CHECKING:
    import datetime as dt
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from episodic.canonical.domain import (
        GenerationEvent,
        GenerationRun,
        JsonMapping,
    )
    from episodic.canonical.generation_run_ports import (
        GenerationRunEventStore,
        GenerationRunPort,
    )
    from episodic.generation.draft_script import (
        DraftScriptRequest,
        DraftScriptResult,
    )


@dc.dataclass(slots=True)
class ScriptedQualityEvaluator:
    """In-process evaluator that returns or raises a scripted outcome."""

    slug: str
    verdict: QualityVerdict | None = None
    error: Exception | None = None
    started: asyncio.Event = dc.field(default_factory=asyncio.Event)

    @property
    def name(self) -> str:
        """The evaluator's stable slug."""
        return self.slug

    async def evaluate(self, subject: EvaluationSubject) -> QualityEvaluation:
        """Return the scripted verdict or raise the scripted error."""
        _ = subject
        self.started.set()
        if self.error is not None:
            raise self.error
        if self.verdict is None:
            msg = "scripted evaluator needs a verdict or an error"
            raise AssertionError(msg)
        return QualityEvaluation(self.slug, self.verdict)


@dc.dataclass(slots=True)
class BlockingQualityEvaluator:
    """Evaluator that blocks until its task is cancelled."""

    slug: str = "blocking-evaluator"
    started: asyncio.Event = dc.field(default_factory=asyncio.Event)

    @property
    def name(self) -> str:
        """The evaluator's stable slug."""
        return self.slug

    async def evaluate(self, subject: EvaluationSubject) -> QualityEvaluation:
        """Block forever, recording that evaluation began."""
        _ = subject
        self.started.set()
        await asyncio.Event().wait()
        msg = "a cancelled evaluator cannot return"
        raise AssertionError(msg)


def passing_evaluator(slug: str = "pedante") -> ScriptedQualityEvaluator:
    """Return an evaluator that passes the draft."""
    return ScriptedQualityEvaluator(slug, QualityVerdict.PASSED)


def failing_evaluator(slug: str = "pedante") -> ScriptedQualityEvaluator:
    """Return an evaluator that rejects the draft."""
    return ScriptedQualityEvaluator(slug, QualityVerdict.FAILED)


def inconclusive_evaluator(slug: str = "pedante") -> ScriptedQualityEvaluator:
    """Return an evaluator with no usable verdict."""
    return ScriptedQualityEvaluator(slug, QualityVerdict.INCONCLUSIVE)


def raising_evaluator(slug: str = "pedante") -> ScriptedQualityEvaluator:
    """Return an evaluator whose adapter raises."""
    return ScriptedQualityEvaluator(slug, error=RuntimeError("evaluator fault"))


@dc.dataclass(slots=True)
class BlockingCostRecorder:
    """Cost recorder that blocks inside the terminal transaction."""

    started: asyncio.Event = dc.field(default_factory=asyncio.Event)
    release: asyncio.Event = dc.field(default_factory=asyncio.Event)
    provider_calls: list[typ.Any] = dc.field(default_factory=list)

    @staticmethod
    async def pin_run_pricing(
        workflow_run_id: str,
        providers: tuple[object, ...],
        billing_period_key: object,
    ) -> None:
        """Accept pricing pins without blocking."""
        _ = (workflow_run_id, providers, billing_period_key)

    async def record_provider_call(self, record: object) -> object:
        """Block until the test releases or cancels it."""
        self.started.set()
        await self.release.wait()
        self.provider_calls.append(record)
        return "entry:blocked"

    async def finalize_run(self, workflow_run_id: str, workflow_node: str) -> object:
        """Return a deterministic roll-up identifier."""
        _ = (self, workflow_run_id, workflow_node)
        return "entry:rollup"


class TaskNameAssertingUnitOfWork(SqlAlchemyUnitOfWork):
    """Unit of work that rejects off-task event appends."""

    async def __aenter__(self) -> SqlAlchemyUnitOfWork:
        """Open the real unit of work and wrap its run store."""
        uow = await super().__aenter__()
        uow.generation_runs = typ.cast(
            "GenerationRunPort",
            _TaskNameAssertingRunStore(uow.generation_runs),
        )
        return uow


class _TaskNameAssertingRunStore:
    """Run store proxy that asserts the appending task's name."""

    def __init__(self, inner: GenerationRunEventStore) -> None:
        """Wrap the store whose appends are checked."""
        self._inner = inner

    def __getattr__(self, name: str) -> object:
        """Delegate every other attribute to the inner store."""
        return getattr(self._inner, name)

    async def append_event(
        self,
        run_id: uuid.UUID,
        *,
        kind: str,
        payload: JsonMapping,
        occurred_at: dt.datetime | None = None,
    ) -> GenerationEvent:
        """Assert the append runs in the run's own launcher task."""
        task = asyncio.current_task()
        expected = f"generation-run-{run_id}"
        if task is None:
            msg = "event appends must run in a task"
            raise AssertionError(msg)
        if task.get_name() != expected:
            msg = f"append for {run_id} ran on task {task.get_name()!r}"
            raise AssertionError(msg)
        return await self._inner.append_event(
            run_id,
            kind=kind,
            payload=payload,
            occurred_at=occurred_at,
        )


async def assert_off_task_append_is_rejected(
    store: GenerationRunEventStore,
    run_id: uuid.UUID,
) -> None:
    """Prove the task-name wrapper rejects an append from another task."""

    async def _append_from_foreign_task() -> None:
        """Append from a task that is not named for the run."""
        await _TaskNameAssertingRunStore(store).append_event(
            run_id,
            kind="foreign",
            payload={},
        )

    task = asyncio.create_task(_append_from_foreign_task(), name="foreign-task")
    try:
        await task
    except AssertionError:
        return
    msg = "the task-name wrapper accepted an append from a foreign task"
    raise AssertionError(msg)


class CancelledDraftGenerator:
    """Draft generator fake that raises ``CancelledError`` from inside itself."""

    def __init__(self) -> None:
        """Create the generator and its start signal."""
        self.started = asyncio.Event()

    async def generate(self, request: DraftScriptRequest) -> DraftScriptResult:
        """Raise cancellation without any external cancellation request."""
        _ = request
        self.started.set()
        raise asyncio.CancelledError


def _qa_gated_run(
    episode_id: uuid.UUID,
    source_bundle_id: uuid.UUID,
) -> GenerationRun:
    """Return a pending QA-gated generation run."""
    return dc.replace(
        _run(episode_id, source_bundle_id),
        quality_mode=QualityMode.QA_GATED,
        qa_status=QaStatus.PENDING,
        skip_qa_rationale=None,
    )


async def prepare_pending_qa_gated_run(
    factory: async_sessionmaker[AsyncSession],
) -> tuple[uuid.UUID, uuid.UUID]:
    """Persist a ready episode and a pending QA-gated generation run."""
    return await _prepare_pending_run(factory, _qa_gated_run)
