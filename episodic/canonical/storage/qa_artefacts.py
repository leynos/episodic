"""SQLAlchemy adapter for durable QA artefacts linked to canonical episodes.

The adapter follows :class:`SqlAlchemyGenerationRunStore` rather than the
generic repository base, because recording needs a savepoint-and-requery
insert: a repeated ``(episode_id, idempotency_key)`` is a replay, and a stored
``ERRORED`` artefact is superseded in place by a later successful recording.
"""

import typing as typ

import sqlalchemy as sa
from sqlalchemy import orm
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from episodic.canonical.qa_artefact_errors import UnsupportedQaArtefactSchemaError
from episodic.canonical.qa_artefacts import QaComplianceStatus
from episodic.operation_observation import OperationObservation

from .integrity_helpers import constraint_name
from .qa_artefact_mappers import (
    evaluation_from_record,
    evaluation_to_record,
    finding_to_record,
    summary_from_record,
)
from .qa_artefact_models import QaEvaluationRecord
from .qa_artefact_outcomes import (
    emit_failed,
    emit_recorded,
    emit_replayed,
    log_outcome,
)
from .qa_artefact_storage_runtime import qa_artefact_storage_runtime

if typ.TYPE_CHECKING:
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession

    from episodic.canonical.qa_artefact_ports import QaEvaluationListRequest
    from episodic.canonical.qa_artefacts import (
        QaEvaluation,
        QaEvaluationSummary,
    )

    from .qa_artefact_storage_runtime import QaArtefactStorageRuntime

# Only these constraints can report a replay. Narrowing matters because the
# caller's unit of work may hold unrelated pending work that this flush also
# sends, and a broad catch would roll it back to our savepoint and call the
# result a replay.
_IDEMPOTENCY_CONSTRAINT = "uq_qa_evaluations_episode_idempotency_key"
_PRIMARY_KEY_CONSTRAINT = "qa_evaluations_pkey"
# A retry of the same evaluation object repeats its identifier as well as its
# episode and key, so PostgreSQL may report the primary-key violation instead of
# the episode/idempotency-key one. Both are replay candidates; the row is then
# matched on the episode and key, which is what separates a retry from an
# unrelated identifier collision.
_REPLAY_CONSTRAINTS = frozenset({_IDEMPOTENCY_CONSTRAINT, _PRIMARY_KEY_CONSTRAINT})


def _evaluation_filters(
    request: QaEvaluationListRequest,
) -> list[sa.ColumnElement[bool]]:
    """Return the shared filter criteria for a page and its unpaged total."""
    filters: list[sa.ColumnElement[bool]] = [
        QaEvaluationRecord.episode_id == request.episode_id
    ]
    if request.evaluator is not None:
        filters.append(QaEvaluationRecord.evaluator == request.evaluator)
    if request.compliance_status is not None:
        filters.append(
            QaEvaluationRecord.compliance_status == request.compliance_status
        )
    return filters


class SqlAlchemyQaArtefactStore:
    """PostgreSQL-backed QA artefact store."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        runtime: QaArtefactStorageRuntime | None = None,
    ) -> None:
        self._session = session
        self._runtime = qa_artefact_storage_runtime(runtime)

    def _observe(
        self,
        operation: str,
        labels: dict[str, str] | None = None,
    ) -> OperationObservation:
        """Return an operation observer bound to the store's runtime."""
        return OperationObservation(
            tracer=self._runtime.tracer,
            metrics=self._runtime.metrics,
            clock=self._runtime.monotonic_clock,
            span_name=f"qa_artefact.{operation}",
            labels={} if labels is None else labels,
        )

    async def record_evaluation(self, evaluation: QaEvaluation) -> QaEvaluation:
        """Persist an evaluation and its findings, replaying or superseding.

        Parameters
        ----------
        evaluation : QaEvaluation
            Evaluation to persist together with its ordered findings.

        Returns
        -------
        QaEvaluation
            The stored artefact. A repeated ``(episode_id, idempotency_key)``
            returns the stored artefact unchanged, except that a stored
            ``ERRORED`` artefact is superseded in place by a later successful
            recording and keeps its identifier.

        Raises
        ------
        sqlalchemy.exc.IntegrityError
            A constraint outside the replay set rejected the rows, or the
            primary key collided on an identifier belonging to a different
            episode or idempotency key; the caller's transaction is intact.
        sqlalchemy.exc.SQLAlchemyError
            The database rejected the statement for another reason.
        """  # ruff: ignore[docstring-extraneous-exception]  # The flush's integrity error is re-raised, not constructed here.
        summary = evaluation.summary_record
        operation = self._observe("record", {"evaluator": summary.evaluator.value})
        with operation:
            # ``begin_nested()`` flushes pending state unconditionally before it
            # opens the savepoint, whatever ``autoflush`` says. Flush the
            # caller's work first, outside the ``try``, so a caller-owned
            # constraint failure propagates without being counted as a QA
            # recording failure.
            await self._session.flush()
            try:
                async with self._session.begin_nested():
                    record = evaluation_to_record(
                        evaluation,
                        created_at=summary.created_at or self._runtime.clock(),
                    )
                    self._session.add(record)
                    await self._session.flush()
            except IntegrityError as err:
                return await self._replay_after_conflict(err, evaluation, operation)
            except SQLAlchemyError:
                emit_failed(self._runtime.metrics, summary, "database_error")
                operation.failed("database_error")
                raise
            emit_recorded(self._runtime.metrics, summary)
            log_outcome(summary, replayed=False, superseded=False)
            operation.succeeded("recorded")
            return await self._require_stored(evaluation.summary_record.id)

    async def get_evaluation(self, evaluation_id: uuid.UUID) -> QaEvaluation | None:
        """Return one evaluation with its findings, or ``None``.

        Parameters
        ----------
        evaluation_id : uuid.UUID
            Identifier of the evaluation to load.

        Returns
        -------
        QaEvaluation | None
            The stored artefact when it exists, otherwise ``None``.

        Raises
        ------
        UnsupportedQaArtefactSchemaError
            If the stored artefact carries a schema version this release
            cannot read.
        """
        operation = self._observe("get")
        with operation:
            record = await self._select_with_findings(
                sa.select(QaEvaluationRecord).where(
                    QaEvaluationRecord.id == evaluation_id
                )
            )
            if record is None:
                operation.succeeded("not_found")
                return None
            try:
                stored = evaluation_from_record(record)
            except UnsupportedQaArtefactSchemaError:
                operation.failed("unsupported_schema")
                raise
            operation.succeeded("success")
            return stored

    async def list_evaluations(
        self,
        request: QaEvaluationListRequest,
    ) -> tuple[list[QaEvaluationSummary], int]:
        """Return one filtered page of evaluation summaries and the total.

        Parameters
        ----------
        request : QaEvaluationListRequest
            Episode scope, optional filters, and the requested page.

        Returns
        -------
        tuple[list[QaEvaluationSummary], int]
            The summaries on the requested page in ``evaluated_at DESC, id
            DESC`` order, and the unpaged total that matches the filters.

        Raises
        ------
        sqlalchemy.exc.SQLAlchemyError
            The database rejected either statement.
        """
        operation = self._observe("list")
        with operation:
            filters = _evaluation_filters(request)
            # Both statements are built from the same criteria so the total
            # cannot describe a different population from the page
            # (INV-FILTER-SOUND).
            page_statement = (
                sa
                .select(QaEvaluationRecord)
                .where(*filters)
                .order_by(
                    QaEvaluationRecord.evaluated_at.desc(),
                    QaEvaluationRecord.id.desc(),
                )
                .limit(request.pagination.limit)
                .offset(request.pagination.offset)
            )
            total_statement = (
                sa
                .select(sa.func.count())
                .select_from(QaEvaluationRecord)
                .where(*filters)
            )
            # A query must not autoflush the caller's staged objects: that
            # would turn a read into a write and attribute a pending constraint
            # failure to a statement that never wrote it. Hold one boundary
            # across both statements so the page and the total see the same
            # snapshot.
            try:
                with self._session.no_autoflush:
                    result = await self._session.execute(page_statement)
                    summaries = [
                        summary_from_record(record) for record in result.scalars()
                    ]
                    total = await self._session.scalar(total_statement)
            except SQLAlchemyError:
                operation.failed("database_error")
                raise
            operation.succeeded("success")
            return summaries, typ.cast("int", total)

    async def _select_with_findings(
        self,
        statement: sa.Select[tuple[QaEvaluationRecord]],
    ) -> QaEvaluationRecord | None:
        """Execute a statement selecting one evaluation, findings included."""
        # As in ``list_evaluations``: a read never flushes the caller's work.
        # Callers that need the write visible flush it explicitly first.
        with self._session.no_autoflush:
            result = await self._session.execute(
                statement.options(
                    orm.selectinload(QaEvaluationRecord.findings)
                ).execution_options(populate_existing=True)
            )
        return result.scalar_one_or_none()

    async def _require_stored(self, evaluation_id: uuid.UUID) -> QaEvaluation:
        """Return a just-written evaluation or fail loudly."""
        record = await self._select_with_findings(
            sa.select(QaEvaluationRecord).where(QaEvaluationRecord.id == evaluation_id)
        )
        if record is None:  # pragma: no cover - the row was written above.
            msg = f"QA evaluation {evaluation_id} is missing after a successful write."
            raise RuntimeError(msg)
        return evaluation_from_record(record)

    async def _replay_after_conflict(
        self,
        err: IntegrityError,
        evaluation: QaEvaluation,
        operation: OperationObservation,
    ) -> QaEvaluation:
        """Return the stored artefact for a replay, or re-raise."""
        summary = evaluation.summary_record
        # Lock the row before deciding whether to supersede it. Without the
        # lock, two concurrent replays can both read the same errored artefact;
        # the loser then replaces findings the winner already replaced and
        # collides on their ordinal instead of replaying the committed result.
        if constraint_name(err) not in _REPLAY_CONSTRAINTS:
            emit_failed(self._runtime.metrics, summary, "integrity_violation")
            operation.failed("integrity_violation")
            raise err
        record = await self._select_with_findings(
            sa
            .select(QaEvaluationRecord)
            .where(
                QaEvaluationRecord.episode_id == summary.episode_id,
                QaEvaluationRecord.idempotency_key == summary.idempotency_key,
            )
            .with_for_update()
        )
        if record is None:
            # The identifier collision named a row outside this episode and
            # key, so this is not a replay and the caller must see it. The
            # category stays distinct from ``integrity_violation`` so a
            # constraint that should have been rejected before the lookup is
            # still visible in the metrics.
            emit_failed(self._runtime.metrics, summary, "conflict_without_row")
            operation.failed("conflict_without_row")
            raise err
        if self._should_supersede(record, evaluation):
            # Read the stored status before superseding it, so the metric names
            # the verdict that was replayed rather than the one just written.
            stored_status = record.compliance_status
            stored = await self._supersede(record, evaluation)
            emit_replayed(self._runtime.metrics, summary, stored_status)
            log_outcome(summary, replayed=True, superseded=True)
            operation.succeeded("superseded")
            return stored
        emit_replayed(self._runtime.metrics, summary, record.compliance_status)
        log_outcome(summary, replayed=True, superseded=False)
        operation.succeeded("replayed")
        return evaluation_from_record(record)

    @staticmethod
    def _should_supersede(
        record: QaEvaluationRecord,
        evaluation: QaEvaluation,
    ) -> bool:
        """Return whether a stored errored artefact may be replaced in place."""
        return (
            record.compliance_status is QaComplianceStatus.ERRORED
            and evaluation.summary_record.compliance_status
            is not QaComplianceStatus.ERRORED
        )

    async def _supersede(
        self,
        record: QaEvaluationRecord,
        evaluation: QaEvaluation,
    ) -> QaEvaluation:
        """Replace the payload and findings of a stored errored artefact."""
        summary = evaluation.summary_record
        operation = self._observe(
            "supersede",
            {"evaluator": summary.evaluator.value},
        )
        with operation:
            try:
                # The savepoint keeps a rejected supersession from taking the
                # caller's unrelated pending work down with it, matching the
                # read-then-replace contract ``record_evaluation`` documents.
                async with self._session.begin_nested():
                    record.evaluator_version = summary.evaluator_version
                    record.artefact_schema_version = summary.artefact_schema_version
                    record.compliance_policy_version = summary.compliance_policy_version
                    record.compliance_status = summary.compliance_status
                    record.summary = summary.summary
                    record.rubric_score = summary.rubric_score
                    record.runtime_estimate_seconds = summary.runtime_estimate_seconds
                    record.finding_count = summary.finding_count
                    record.evaluator_metadata = summary.evaluator_metadata
                    record.evaluated_at = summary.evaluated_at
                    record.generation_run_id = summary.generation_run_id
                    # The deletes must reach the database before the
                    # replacements are inserted: one flush emits inserts first,
                    # so ordinal 0 of the replacement would collide with
                    # ordinal 0 of the errored recording.
                    record.findings.clear()
                    await self._session.flush()
                    record.findings = [
                        finding_to_record(finding, evaluation_id=record.id)
                        for finding in evaluation.findings
                    ]
                    await self._session.flush()
            except SQLAlchemyError:
                emit_failed(self._runtime.metrics, summary, "supersede_failed")
                operation.failed("supersede_failed")
                raise
            operation.succeeded("superseded")
            return await self._require_stored(record.id)
