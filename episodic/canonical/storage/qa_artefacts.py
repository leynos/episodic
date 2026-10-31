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

from episodic.canonical.qa_artefacts import QaComplianceStatus
from episodic.logging import log_event as _log_event

from .integrity_helpers import constraint_name
from .qa_artefact_mappers import (
    evaluation_from_record,
    evaluation_to_record,
    finding_to_record,
    summary_from_record,
)
from .qa_artefact_models import QaEvaluationRecord
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

# Only this constraint reports a replay. Narrowing matters because the caller's
# unit of work may hold unrelated pending work that this flush also sends, and a
# broad catch would roll it back to our savepoint and call the result a replay.
_IDEMPOTENCY_CONSTRAINT = "uq_qa_evaluations_episode_idempotency_key"


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
            A constraint other than the episode/idempotency-key uniqueness
            constraint rejected the rows; the caller's transaction is intact.
        sqlalchemy.exc.SQLAlchemyError
            The database rejected the statement for another reason.
        """  # ruff: ignore[docstring-extraneous-exception]  # The flush's integrity error is re-raised, not constructed here.
        summary = evaluation.summary_record
        try:
            async with self._session.begin_nested():
                record = evaluation_to_record(
                    evaluation,
                    created_at=summary.created_at or self._runtime.clock(),
                )
                self._session.add(record)
                await self._session.flush()
        except IntegrityError as err:
            return await self._replay_after_conflict(err, evaluation)
        except SQLAlchemyError:
            self._emit_failed(summary, "database_error")
            raise
        self._emit_recorded(summary)
        self._log_outcome(summary, replayed=False, superseded=False)
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
        """
        record = await self._select_with_findings(
            sa.select(QaEvaluationRecord).where(QaEvaluationRecord.id == evaluation_id)
        )
        if record is None:
            return None
        return evaluation_from_record(record)

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
        """
        filters = _evaluation_filters(request)
        # Both statements are built from the same criteria so the total cannot
        # describe a different population from the page (INV-FILTER-SOUND).
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
            sa.select(sa.func.count()).select_from(QaEvaluationRecord).where(*filters)
        )
        result = await self._session.execute(page_statement)
        summaries = [summary_from_record(record) for record in result.scalars()]
        total = await self._session.scalar(total_statement)
        return summaries, typ.cast("int", total)

    async def _select_with_findings(
        self,
        statement: sa.Select[tuple[QaEvaluationRecord]],
    ) -> QaEvaluationRecord | None:
        """Execute a statement selecting one evaluation, findings included."""
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
    ) -> QaEvaluation:
        """Return the stored artefact for a replay, or re-raise."""
        summary = evaluation.summary_record
        if constraint_name(err) != _IDEMPOTENCY_CONSTRAINT:
            self._emit_failed(summary, "integrity_violation")
            raise err
        record = await self._select_with_findings(
            sa.select(QaEvaluationRecord).where(
                QaEvaluationRecord.episode_id == summary.episode_id,
                QaEvaluationRecord.idempotency_key == summary.idempotency_key,
            )
        )
        if record is None:  # pragma: no cover - the unique violation proves a row.
            self._emit_failed(summary, "conflict_without_row")
            raise err
        if self._should_supersede(record, evaluation):
            # Read the stored status before superseding it, so the metric names
            # the verdict that was replayed rather than the one just written.
            stored_status = record.compliance_status
            stored = await self._supersede(record, evaluation)
            self._emit_replayed(summary, stored_status)
            self._log_outcome(summary, replayed=True, superseded=True)
            return stored
        self._emit_replayed(summary, record.compliance_status)
        self._log_outcome(summary, replayed=True, superseded=False)
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
        # The deletes must reach the database before the replacements are
        # inserted: one flush emits inserts first, so ordinal 0 of the
        # replacement would collide with ordinal 0 of the errored recording.
        record.findings.clear()
        await self._session.flush()
        record.findings = [
            finding_to_record(finding, evaluation_id=record.id)
            for finding in evaluation.findings
        ]
        await self._session.flush()
        return await self._require_stored(record.id)

    def _emit_recorded(self, summary: QaEvaluationSummary) -> None:
        """Count a first-time recording."""
        self._runtime.metrics.increment_counter(
            "qa_evaluation_recorded",
            labels={
                "evaluator": summary.evaluator.value,
                "compliance_status": summary.compliance_status.value,
            },
        )

    def _emit_replayed(
        self,
        summary: QaEvaluationSummary,
        stored_status: QaComplianceStatus,
    ) -> None:
        """Count a replay of an existing artefact."""
        self._runtime.metrics.increment_counter(
            "qa_evaluation_replayed",
            labels={
                "evaluator": summary.evaluator.value,
                "stored_status": stored_status.value,
            },
        )

    def _emit_failed(self, summary: QaEvaluationSummary, error_category: str) -> None:
        """Count a failed recording under a bounded error category."""
        self._runtime.metrics.increment_counter(
            "qa_evaluation_record_failed",
            labels={
                "evaluator": summary.evaluator.value,
                "error_category": error_category,
            },
        )

    @staticmethod
    def _log_outcome(
        summary: QaEvaluationSummary,
        *,
        replayed: bool,
        superseded: bool,
    ) -> None:
        """Log the recording outcome without any finding text."""
        _log_event(
            "info",
            "sql_qa_artefact_store.record_evaluation",
            evaluator=summary.evaluator.value,
            episode_id=str(summary.episode_id),
            replayed=replayed,
            superseded=superseded,
        )
