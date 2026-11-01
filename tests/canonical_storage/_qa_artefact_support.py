"""Shared fixtures for QA artefact storage tests.

Builds the canonical episode prerequisites that ``qa_evaluations`` links to,
and composed evaluations whose identifiers are fresh per call. The property
suites need a new episode per example, so identifiers are never module-level
constants here.
"""

import dataclasses as dc
import datetime as dt
import typing as typ
import uuid

import sqlalchemy as sa

from episodic.canonical.domain import (
    ApprovalState,
    CanonicalEpisode,
    EpisodeStatus,
    IngestionJob,
    IngestionStatus,
    SeriesProfile,
    TeiHeader,
)
from episodic.canonical.qa_artefacts import (
    QA_ARTEFACT_SCHEMA_VERSION,
    QA_COMPLIANCE_POLICY_VERSION,
    QaComplianceStatus,
    QaEvaluation,
    QaEvaluationSummary,
    QaEvaluator,
    QaFindingSeverity,
)
from episodic.canonical.storage import (
    Base,
    QaEvaluationRecord,
    QaFindingRecord,
    SqlAlchemyUnitOfWork,
)
from tests.fixtures.qa_artefact_builders import EVALUATED_AT, finding

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


async def count_rows(session: AsyncSession, model: type[Base]) -> int:
    """Return the number of rows in ``model``'s table."""
    total = await session.scalar(sa.select(sa.func.count()).select_from(model))
    return typ.cast("int", total)


async def count_artefacts_for(
    session: AsyncSession,
    episode_ids: list[uuid.UUID],
) -> tuple[int, int]:
    """Return the evaluation and finding counts scoped to ``episode_ids``.

    The migrated py-pglite schema is reset per test function rather than per
    Hypothesis example, so a property test must not count whole tables.

    Returns
    -------
    tuple[int, int]
        Evaluation rows and finding rows belonging to those episodes.
    """
    evaluations = await session.scalar(
        sa
        .select(sa.func.count())
        .select_from(QaEvaluationRecord)
        .where(QaEvaluationRecord.episode_id.in_(episode_ids))
    )
    findings = await session.scalar(
        sa
        .select(sa.func.count())
        .select_from(QaFindingRecord)
        .join(
            QaEvaluationRecord,
            QaFindingRecord.evaluation_id == QaEvaluationRecord.id,
        )
        .where(QaEvaluationRecord.episode_id.in_(episode_ids))
    )
    return typ.cast("int", evaluations), typ.cast("int", findings)


def episode_records(
    *,
    episode_id: uuid.UUID,
) -> tuple[SeriesProfile, TeiHeader, CanonicalEpisode]:
    """Return an episode and the series and header rows it references."""
    now = dt.datetime.now(dt.UTC)
    series = SeriesProfile(
        id=uuid.uuid7(),
        # The whole hex keeps the slug unique: a UUIDv7's leading bits are its
        # timestamp, so a prefix repeats for episodes created in one millisecond.
        slug=f"qa-{episode_id.hex}",
        title="QA artefact tests",
        description="Episodes that carry recorded evaluations.",
        configuration={},
        guardrails={},
        created_at=now,
        updated_at=now,
    )
    header = TeiHeader(
        id=uuid.uuid7(),
        title="QA artefact episode",
        payload={},
        raw_xml="<TEI/>",
        created_at=now,
        updated_at=now,
    )
    episode = CanonicalEpisode(
        id=episode_id,
        series_profile_id=series.id,
        tei_header_id=header.id,
        title=header.title,
        tei_xml=header.raw_xml,
        status=EpisodeStatus.DRAFT,
        approval_state=ApprovalState.DRAFT,
        created_at=now,
        updated_at=now,
    )
    return series, header, episode


async def create_episode(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    episode_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """Persist a fresh series, header, and episode, returning the episode id."""
    series, header, episode = episode_records(
        episode_id=uuid.uuid7() if episode_id is None else episode_id,
    )
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        await uow.series_profiles.add(series)
        await uow.tei_headers.add(header)
        await uow.commit()
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        await uow.episodes.add(episode)
        await uow.commit()
    return episode.id


async def create_ingestion_job(
    session_factory: async_sessionmaker[AsyncSession],
    episode_id: uuid.UUID,
) -> uuid.UUID:
    """Persist a completed ingestion job targeting ``episode_id``."""
    now = dt.datetime.now(dt.UTC)
    async with SqlAlchemyUnitOfWork(session_factory) as uow:
        episode = await uow.episodes.get(episode_id)
        if episode is None:  # pragma: no cover - callers pass a stored episode.
            msg = f"episode {episode_id} is missing."
            raise RuntimeError(msg)
        job = IngestionJob(
            id=uuid.uuid7(),
            series_profile_id=episode.series_profile_id,
            target_episode_id=episode.id,
            status=IngestionStatus.COMPLETED,
            requested_at=now,
            started_at=now,
            completed_at=now,
            error_message=None,
            created_at=now,
            updated_at=now,
        )
        await uow.ingestion_jobs.add(job)
        await uow.commit()
    return job.id


@dc.dataclass(frozen=True, slots=True)
class EvaluationOptions:
    """Optional field values for a composed evaluation.

    Attributes
    ----------
    compliance_status : QaComplianceStatus
        Verdict to record.
    evaluator : QaEvaluator
        Evaluator that produced the artefact.
    evaluated_at : dt.datetime
        Timezone-aware instant at which the evaluator ran.
    severities : tuple[QaFindingSeverity, ...]
        One finding per entry, in emission order.
    generation_run_id : uuid.UUID | None
        Optional launcher run that triggered the evaluation.
    created_at : dt.datetime | None
        Optional storage time, so a round trip can compare whole artefacts.
    """

    compliance_status: QaComplianceStatus = QaComplianceStatus.COMPLIANT
    evaluator: QaEvaluator = QaEvaluator.PEDANTE
    evaluated_at: dt.datetime = EVALUATED_AT
    severities: tuple[QaFindingSeverity, ...] = ()
    generation_run_id: uuid.UUID | None = None
    created_at: dt.datetime | None = None


# Sharing one instance is safe because the dataclass is frozen, and it keeps the
# call expression out of the signature so a default cannot look like a mutable
# default to the linters.
_DEFAULT_EVALUATION_OPTIONS = EvaluationOptions()


def make_evaluation(
    episode_id: uuid.UUID,
    *,
    idempotency_key: str,
    options: EvaluationOptions = _DEFAULT_EVALUATION_OPTIONS,
) -> QaEvaluation:
    """Return a valid evaluation with one finding per requested severity.

    Parameters
    ----------
    episode_id : uuid.UUID
        Episode the evaluation is recorded against.
    idempotency_key : str
        Key that makes a repeated recording replay this artefact.
    options : EvaluationOptions
        Optional field values; the defaults match a compliant Pedante run.

    Returns
    -------
    QaEvaluation
        The composed evaluation, with fresh identifiers.
    """
    evaluation_id = uuid.uuid7()
    findings = tuple(
        finding(
            finding_id=uuid.uuid7(),
            evaluation_id=evaluation_id,
            ordinal=ordinal,
            severity=severity,
            code=f"code-{ordinal}",
            summary=f"Finding {ordinal}.",
        )
        for ordinal, severity in enumerate(options.severities)
    )
    return QaEvaluation(
        summary_record=QaEvaluationSummary(
            id=evaluation_id,
            episode_id=episode_id,
            evaluator=options.evaluator,
            evaluator_version="pedante-1.0.0",
            artefact_schema_version=QA_ARTEFACT_SCHEMA_VERSION,
            compliance_policy_version=QA_COMPLIANCE_POLICY_VERSION,
            compliance_status=options.compliance_status,
            evaluated_at=options.evaluated_at,
            idempotency_key=idempotency_key,
            finding_count=len(findings),
            generation_run_id=options.generation_run_id,
            created_at=options.created_at,
        ),
        findings=findings,
    )
