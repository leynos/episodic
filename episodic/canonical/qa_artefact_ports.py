"""Persistence port for QA artefacts linked to canonical episodes.

The port is a structural :class:`typing.Protocol`, so a storage adapter
conforms by implementing the three methods rather than by subclassing this
module. Test doubles can therefore implement only what they exercise.
"""

import dataclasses as dc
import typing as typ

if typ.TYPE_CHECKING:
    import uuid

    from .pagination import Pagination
    from .qa_artefacts import (
        QaComplianceStatus,
        QaEvaluation,
        QaEvaluationSummary,
        QaEvaluator,
    )


@dc.dataclass(frozen=True, slots=True)
class QaEvaluationListRequest:
    """Filter and page selectors for a QA evaluation listing."""

    episode_id: uuid.UUID
    pagination: Pagination
    evaluator: QaEvaluator | None = None
    compliance_status: QaComplianceStatus | None = None


class QaArtefactRepository(typ.Protocol):
    """Persistence port for QA artefacts linked to canonical episodes."""

    async def record_evaluation(self, evaluation: QaEvaluation) -> QaEvaluation:
        """Persist an evaluation and its findings.

        Returns the stored artefact with its findings populated. A repeat of an
        existing ``(episode_id, idempotency_key)`` returns the stored artefact
        unchanged, except that a stored artefact whose compliance status is
        ``ERRORED`` is superseded in place by a later successful recording,
        keeping its identifier.

        Parameters
        ----------
        evaluation : QaEvaluation
            Evaluation to persist together with its ordered findings.

        Returns
        -------
        QaEvaluation
            The stored artefact, with findings in ordinal order.
        """
        ...

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
        ...

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
            The summaries on the requested page, and the unpaged total that
            matches the filters.
        """
        ...
