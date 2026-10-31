"""Unit tests for the QA evaluation idempotency key.

Discharges ``INV-KEY-DETERMINISM``: the key is a function of exactly the inputs
the store's uniqueness constraint depends on, so a replay returns the stored
artefact and a genuinely different evaluation does not.
"""

import dataclasses as dc
import datetime as dt
import typing as typ

import pytest

from episodic.canonical.qa_artefact_recording import (
    evaluation_from_pedante,
    qa_idempotency_key,
)
from episodic.canonical.qa_artefacts import QaEvaluator
from tests.fixtures.qa_artefact_recording_builders import (
    EPISODE_ID,
    EVALUATED_AT,
    EVALUATION_ID,
    GENERATION_RUN_ID,
    TEI_CONTENT_HASH,
    pedante_result,
)

if typ.TYPE_CHECKING:
    import uuid


@dc.dataclass(frozen=True, slots=True)
class _KeyInputs:
    """The five inputs the idempotency key is documented to depend on."""

    evaluator: QaEvaluator = QaEvaluator.PEDANTE
    evaluator_version: str = "1"
    compliance_policy_version: int = 1
    tei_content_hash: str = "abc123"
    generation_run_id: uuid.UUID | None = None

    def derive(self) -> str:
        """Return the key these inputs produce."""
        return qa_idempotency_key(
            evaluator=self.evaluator,
            evaluator_version=self.evaluator_version,
            compliance_policy_version=self.compliance_policy_version,
            tei_content_hash=self.tei_content_hash,
            generation_run_id=self.generation_run_id,
        )


def _fixed_identifiers() -> uuid.UUID:
    """Return the shared evaluation identifier."""
    return EVALUATION_ID


def _key_reading_at(evaluated_at: dt.datetime) -> str:
    """Record one identical outcome as if the clock read ``evaluated_at``."""
    evaluation = evaluation_from_pedante(
        pedante_result(),
        episode_id=EPISODE_ID,
        tei_content_hash=TEI_CONTENT_HASH,
        evaluated_at=evaluated_at,
        generation_run_id=GENERATION_RUN_ID,
        uuid_factory=_fixed_identifiers,
    )
    return evaluation.summary_record.idempotency_key


def test_key_uses_the_documented_format() -> None:
    """The idempotency key spells out every input it depends on."""
    with_run = qa_idempotency_key(
        evaluator=QaEvaluator.PEDANTE,
        evaluator_version="1",
        compliance_policy_version=2,
        tei_content_hash="abc123",
        generation_run_id=GENERATION_RUN_ID,
    )
    without_run = qa_idempotency_key(
        evaluator=QaEvaluator.CHRONO,
        evaluator_version="3",
        compliance_policy_version=1,
        tei_content_hash="abc123",
        generation_run_id=None,
    )

    assert with_run == (f"qa:pedante:v1:policy:2:tei:abc123:run:{GENERATION_RUN_ID}"), (
        "the key did not follow the documented format"
    )
    assert without_run == "qa:chrono:v3:policy:1:tei:abc123:run:-", (
        "an absent run should be spelled with a placeholder, not omitted"
    )


@pytest.mark.parametrize("evaluator", list(QaEvaluator))
def test_every_evaluator_has_a_deterministic_key(evaluator: QaEvaluator) -> None:
    """Two independent derivations from equal inputs agree for each evaluator."""
    inputs = dc.replace(_KeyInputs(), evaluator=evaluator, evaluator_version="7")

    assert inputs.derive() == inputs.derive(), (
        f"{evaluator.value} produced different keys for equal inputs"
    )


@pytest.mark.parametrize(
    "changed",
    [
        dc.replace(_KeyInputs(), evaluator=QaEvaluator.CHRONO),
        dc.replace(_KeyInputs(), evaluator_version="2"),
        dc.replace(_KeyInputs(), compliance_policy_version=2),
        dc.replace(_KeyInputs(), tei_content_hash="def456"),
        dc.replace(_KeyInputs(), generation_run_id=GENERATION_RUN_ID),
    ],
    ids=[
        "evaluator",
        "evaluator_version",
        "compliance_policy_version",
        "tei_content_hash",
        "generation_run_id",
    ],
)
def test_changing_any_input_changes_the_key(changed: _KeyInputs) -> None:
    """Every dependency of the key is load-bearing."""
    assert changed.derive() != _KeyInputs().derive(), (
        "the changed input did not change the key"
    )


def test_key_ignores_the_clock_reading() -> None:
    """A minter that folded in the evaluation time would defeat replay."""
    later = EVALUATED_AT + dt.timedelta(hours=2)

    assert _key_reading_at(EVALUATED_AT) == _key_reading_at(later), (
        "the idempotency key changed with the clock"
    )
