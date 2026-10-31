"""Seed QA-artefact retrieval scenarios through the recording service.

The REST API is retrieval-only, so the behavioural steps and the API
integration tests both seed evaluations through the same recording service the
launcher will call. Keeping the episode setup, the fixed evaluator timestamps,
and the identifiers here ensures the two suites observe identical artefacts.
"""

import dataclasses as dc
import datetime as dt
import typing as typ
import uuid

from episodic.canonical.domain import EpisodeTeiUpdate
from episodic.canonical.generation_quality import QaStatus
from episodic.canonical.qa_artefact_recording import qa_idempotency_key
from episodic.canonical.qa_artefact_service import (
    QaEvaluationRecordingRequest,
    QaEvaluatorFailure,
    record_qa_evaluation,
)
from episodic.canonical.qa_artefacts import (
    QA_ARTEFACT_SCHEMA_VERSION,
    QA_COMPLIANCE_POLICY_VERSION,
    QaComplianceStatus,
    QaEvaluation,
    QaEvaluationSummary,
    QaEvaluator,
)
from episodic.qa.pedante.types import (
    ClaimKind,
    FindingSeverity,
    PedanteEvaluationResult,
    SupportLevel,
)
from tests.fixtures.api import api_async_client
from tests.fixtures.generation_run_api import (
    create_ready_ingestion_job,
    generation_payload,
)
from tests.fixtures.qa_artefact_recording_builders import (
    chrono_estimate,
    pedante_finding,
    pedante_result,
)

if typ.TYPE_CHECKING:
    from episodic.api.dependencies import ApiDependencies
    from episodic.canonical.qa_artefact_service import QaEvaluationOutcome

PRINCIPAL_A = {"Authorization": "Bearer principal-a"}
PRINCIPAL_B = {"Authorization": "Bearer principal-b"}

GENERATED_TEI = (
    '<TEI xmlns="http://www.tei-c.org/ns/1.0"><teiHeader><fileDesc>'
    "<titleStmt><title>QA retrieval fixture</title></titleStmt>"
    "<publicationStmt><p>Unpublished fixture.</p></publicationStmt>"
    "<sourceDesc><p>Created for retrieval tests.</p></sourceDesc>"
    "</fileDesc></teiHeader><text><body>"
    "<p>Spoken script text for QA retrieval.</p></body></text></TEI>"
)

ANTHEM_EVALUATOR_VERSION = "anthem-1.0"
ANTHEM_ERROR_CATEGORY = "provider_timeout"

_BACKGROUND_START = dt.datetime(2026, 10, 31, 10, 0, tzinfo=dt.UTC)
PEDANTE_EVALUATED_AT = _BACKGROUND_START
CHRONO_EVALUATED_AT = _BACKGROUND_START + dt.timedelta(minutes=5)
ANTHEM_EVALUATED_AT = _BACKGROUND_START + dt.timedelta(minutes=10)
ANTHEM_SUCCESS_EVALUATED_AT = ANTHEM_EVALUATED_AT + dt.timedelta(minutes=5)

PEDANTE_EVALUATION_ID = uuid.UUID("0199a0c2-0000-7000-8000-000000000001")
CHRONO_EVALUATION_ID = uuid.UUID("0199a0c2-0000-7000-8000-000000000002")
ANTHEM_EVALUATION_ID = uuid.UUID("0199a0c2-0000-7000-8000-000000000003")
ANTHEM_SUCCESS_EVALUATION_ID = uuid.UUID("0199a0c2-0000-7000-8000-000000000004")

_PEDANTE_SUMMARY = "Three claims were checked."


@dc.dataclass(frozen=True, slots=True)
class QaEpisodeFixture:
    """Identifiers and content hash of one generated, QA-evaluated episode.

    Attributes
    ----------
    episode_id : uuid.UUID
        Canonical episode the evaluations belong to.
    generation_run_id : uuid.UUID
        Launcher run that produced the generated draft.
    tei_content_hash : str
        Hash of the TEI draft the evaluations assessed.
    """

    episode_id: uuid.UUID
    generation_run_id: uuid.UUID
    tei_content_hash: str


@dc.dataclass(frozen=True, slots=True)
class _EvaluationSlot:
    """One evaluator outcome scheduled at a fixed time and identifier."""

    evaluated_at: dt.datetime
    outcome: QaEvaluationOutcome
    evaluation_id: uuid.UUID


def require[RequiredValue](
    value: RequiredValue | None,
    label: str,
) -> RequiredValue:
    """Return initialized scenario state or fail with a useful assertion."""
    assert value is not None, f"Expected {label} to be initialized."
    return value


async def create_generated_episode(
    dependencies: ApiDependencies,
    *,
    key_prefix: str = "qa-retrieval",
) -> QaEpisodeFixture:
    """Create an owned episode with a generated TEI draft."""
    async with api_async_client(dependencies) as client:
        job_id = await create_ready_ingestion_job(
            client,
            headers=PRINCIPAL_A,
            key_prefix=key_prefix,
        )
        run = await client.post(
            f"/v1/ingestion-jobs/{job_id}/generation-runs",
            headers={**PRINCIPAL_A, "Idempotency-Key": f"{key_prefix}-run-key"},
            json=generation_payload(),
        )
        assert run.status_code == 202, run.text
        payload = typ.cast("dict[str, object]", run.json())
        episode_id = uuid.UUID(typ.cast("str", payload["episode_id"]))
        generation_run_id = uuid.UUID(typ.cast("str", payload["id"]))

    async with dependencies.uow_factory() as uow:
        episode = await uow.episodes.update(
            episode_id,
            update=EpisodeTeiUpdate(
                tei_xml=GENERATED_TEI,
                qa_status=QaStatus.SKIPPED,
                last_generation_run_id=generation_run_id,
                expected_revision=1,
                updated_at=_BACKGROUND_START - dt.timedelta(minutes=5),
            ),
        )
        await uow.commit()

    assert episode.tei_content_hash is not None, "Expected a persisted TEI hash."
    return QaEpisodeFixture(
        episode_id=episode_id,
        generation_run_id=generation_run_id,
        tei_content_hash=episode.tei_content_hash,
    )


def _pedante_outcome() -> PedanteEvaluationResult:
    """Return a Pedante result with three findings, exactly one blocking."""
    return pedante_result(
        pedante_finding(
            claim_id="claim-1",
            claim_text="The archive holds the earliest recording.",
            claim_kind=ClaimKind.DIRECT_QUOTE,
            support_level=SupportLevel.CITATION_ABSENT,
            severity=FindingSeverity.HIGH,
            summary="The opening claim has no citation.",
            remediation="Cite the archive catalogue entry.",
            cited_source_ids=(),
        ),
        pedante_finding(
            claim_id="claim-2",
            claim_text="The recording dates from 1954.",
            claim_kind=ClaimKind.DIRECT_QUOTE,
            support_level=SupportLevel.ACCURATE_QUOTATION,
            severity=FindingSeverity.LOW,
            summary="The quotation matches the transcript.",
            remediation="No change required.",
            cited_source_ids=("src-1",),
        ),
        pedante_finding(
            claim_id="claim-3",
            claim_text="The session was recorded in winter.",
            claim_kind=ClaimKind.TRANSPLANTED_CLAIM,
            support_level=SupportLevel.ACCURATE_RESTATEMENT,
            severity=FindingSeverity.MEDIUM,
            summary="The restatement is faithful.",
            remediation="No change required.",
            cited_source_ids=("src-2",),
        ),
        summary=_PEDANTE_SUMMARY,
        model="pedante-test-model",
        provider_response_id="pedante-response-1",
    )


async def _record(
    dependencies: ApiDependencies,
    episode: QaEpisodeFixture,
    slot: _EvaluationSlot,
) -> QaEvaluation:
    """Record the outcome assigned to one evaluation slot."""
    async with dependencies.uow_factory() as uow:
        recorded = await record_qa_evaluation(
            uow,
            QaEvaluationRecordingRequest(
                episode_id=episode.episode_id,
                tei_content_hash=episode.tei_content_hash,
                evaluated_at=slot.evaluated_at,
                outcome=slot.outcome,
                generation_run_id=episode.generation_run_id,
                uuid_factory=lambda: slot.evaluation_id,
            ),
        )
        await uow.commit()
    return recorded


async def record_pedante_evaluation(
    dependencies: ApiDependencies,
    episode: QaEpisodeFixture,
) -> uuid.UUID:
    """Record the background Pedante evaluation and return its identifier."""
    recorded = await _record(
        dependencies,
        episode,
        _EvaluationSlot(
            evaluated_at=PEDANTE_EVALUATED_AT,
            outcome=_pedante_outcome(),
            evaluation_id=PEDANTE_EVALUATION_ID,
        ),
    )
    return recorded.summary_record.id


async def record_chrono_evaluation(
    dependencies: ApiDependencies,
    episode: QaEpisodeFixture,
) -> uuid.UUID:
    """Record the background Chrono estimate and return its identifier."""
    recorded = await _record(
        dependencies,
        episode,
        _EvaluationSlot(
            evaluated_at=CHRONO_EVALUATED_AT,
            outcome=chrono_estimate(),
            evaluation_id=CHRONO_EVALUATION_ID,
        ),
    )
    return recorded.summary_record.id


async def record_anthem_failure(
    dependencies: ApiDependencies,
    episode: QaEpisodeFixture,
) -> uuid.UUID:
    """Record the background Anthem failure and return its identifier."""
    recorded = await _record(
        dependencies,
        episode,
        _EvaluationSlot(
            evaluated_at=ANTHEM_EVALUATED_AT,
            outcome=QaEvaluatorFailure(
                evaluator=QaEvaluator.ANTHEM,
                evaluator_version=ANTHEM_EVALUATOR_VERSION,
                error_category=ANTHEM_ERROR_CATEGORY,
                summary="Anthem did not respond before the deadline.",
            ),
            evaluation_id=ANTHEM_EVALUATION_ID,
        ),
    )
    return recorded.summary_record.id


async def record_anthem_success(
    dependencies: ApiDependencies,
    episode: QaEpisodeFixture,
) -> uuid.UUID:
    """Record a successful Anthem retry that supersedes the failure in place."""
    summary_record = QaEvaluationSummary(
        id=ANTHEM_SUCCESS_EVALUATION_ID,
        episode_id=episode.episode_id,
        evaluator=QaEvaluator.ANTHEM,
        evaluator_version=ANTHEM_EVALUATOR_VERSION,
        artefact_schema_version=QA_ARTEFACT_SCHEMA_VERSION,
        compliance_policy_version=QA_COMPLIANCE_POLICY_VERSION,
        compliance_status=QaComplianceStatus.COMPLIANT,
        evaluated_at=ANTHEM_SUCCESS_EVALUATED_AT,
        idempotency_key=qa_idempotency_key(
            evaluator=QaEvaluator.ANTHEM,
            evaluator_version=ANTHEM_EVALUATOR_VERSION,
            compliance_policy_version=QA_COMPLIANCE_POLICY_VERSION,
            tei_content_hash=episode.tei_content_hash,
            generation_run_id=episode.generation_run_id,
        ),
        finding_count=0,
        generation_run_id=episode.generation_run_id,
        summary="Anthem completed on retry.",
    )
    async with dependencies.uow_factory() as uow:
        stored = await uow.qa_artefacts.record_evaluation(
            QaEvaluation(summary_record=summary_record)
        )
        await uow.commit()
    return stored.summary_record.id


async def record_background_evaluations(
    dependencies: ApiDependencies,
    episode: QaEpisodeFixture,
) -> None:
    """Record the three evaluations every retrieval scenario starts from."""
    await record_pedante_evaluation(dependencies, episode)
    await record_chrono_evaluation(dependencies, episode)
    await record_anthem_failure(dependencies, episode)
