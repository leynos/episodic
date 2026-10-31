"""SQLAlchemy models for durable QA artefacts.

One evaluation row carries the evaluator's verdict and the versions that
produced it; its findings live in a child table because roadmap items 4.4.1 and
4.4.2 aggregate individual findings across episodes.
"""

import datetime as dt  # ruff: ignore[typing-only-standard-library-import]  # SQLAlchemy evaluates annotations at runtime.
import decimal  # ruff: ignore[typing-only-standard-library-import]  # SQLAlchemy evaluates annotations at runtime.
import uuid  # ruff: ignore[typing-only-standard-library-import]  # SQLAlchemy evaluates annotations at runtime.

import sqlalchemy as sa
from sqlalchemy import orm
from sqlalchemy.dialects import postgresql

from episodic.canonical.domain import (  # ruff: ignore[typing-only-first-party-import]  # SQLAlchemy evaluates annotations at runtime.
    JsonMapping,
)
from episodic.canonical.qa_artefacts import (  # ruff: ignore[typing-only-first-party-import]  # SQLAlchemy evaluates annotations at runtime.
    QaComplianceStatus,
    QaEvaluator,
    QaFindingSeverity,
)

from .models_base import (
    QA_COMPLIANCE_STATUS,
    QA_EVALUATOR,
    QA_FINDING_SEVERITY,
    Base,
)

_EMPTY_JSON_OBJECT = sa.text("'{}'::jsonb")
_EMPTY_JSON_ARRAY = sa.text("'[]'::jsonb")


class QaEvaluationRecord(Base):
    """SQLAlchemy model for one recorded evaluator invocation."""

    __tablename__ = "qa_evaluations"
    __table_args__ = (
        sa.UniqueConstraint(
            "episode_id",
            "idempotency_key",
            name="uq_qa_evaluations_episode_idempotency_key",
        ),
        sa.CheckConstraint(
            "rubric_score IS NULL OR (rubric_score >= 0 AND rubric_score <= 1)",
            name="ck_qa_evaluations_rubric_score_unit_interval",
        ),
        sa.CheckConstraint(
            "runtime_estimate_seconds IS NULL OR runtime_estimate_seconds >= 0",
            name="ck_qa_evaluations_runtime_estimate_non_negative",
        ),
        sa.CheckConstraint(
            "finding_count >= 0",
            name="ck_qa_evaluations_finding_count_non_negative",
        ),
        # `id` is part of the sort key because identifiers are UUIDv7, so it
        # makes otherwise-tied timestamps page deterministically.
        sa.Index(
            "ix_qa_evaluations_episode_evaluated_at",
            "episode_id",
            sa.desc("evaluated_at"),
            sa.desc("id"),
        ),
        sa.Index(
            "ix_qa_evaluations_episode_evaluator_evaluated_at",
            "episode_id",
            "evaluator",
            sa.desc("evaluated_at"),
            sa.desc("id"),
        ),
    )

    id: orm.Mapped[uuid.UUID] = orm.mapped_column(
        postgresql.UUID(as_uuid=True),
        primary_key=True,
    )
    episode_id: orm.Mapped[uuid.UUID] = orm.mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("episodes.id", ondelete="CASCADE"),
        nullable=False,
    )
    generation_run_id: orm.Mapped[uuid.UUID | None] = orm.mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("generation_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    evaluator: orm.Mapped[QaEvaluator] = orm.mapped_column(
        QA_EVALUATOR,
        nullable=False,
    )
    evaluator_version: orm.Mapped[str] = orm.mapped_column(sa.Text, nullable=False)
    artefact_schema_version: orm.Mapped[int] = orm.mapped_column(
        sa.Integer,
        nullable=False,
    )
    compliance_policy_version: orm.Mapped[int] = orm.mapped_column(
        sa.Integer,
        nullable=False,
    )
    compliance_status: orm.Mapped[QaComplianceStatus] = orm.mapped_column(
        QA_COMPLIANCE_STATUS,
        nullable=False,
    )
    summary: orm.Mapped[str] = orm.mapped_column(
        sa.Text,
        nullable=False,
        server_default="",
    )
    rubric_score: orm.Mapped[decimal.Decimal | None] = orm.mapped_column(
        sa.Numeric(5, 4),
        nullable=True,
    )
    runtime_estimate_seconds: orm.Mapped[int | None] = orm.mapped_column(
        sa.Integer,
        nullable=True,
    )
    finding_count: orm.Mapped[int] = orm.mapped_column(
        sa.Integer,
        nullable=False,
        server_default="0",
    )
    evaluator_metadata: orm.Mapped[JsonMapping] = orm.mapped_column(
        postgresql.JSONB,
        nullable=False,
        server_default=_EMPTY_JSON_OBJECT,
    )
    idempotency_key: orm.Mapped[str] = orm.mapped_column(sa.Text, nullable=False)
    evaluated_at: orm.Mapped[dt.datetime] = orm.mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
    )
    created_at: orm.Mapped[dt.datetime] = orm.mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )

    findings: orm.Mapped[list[QaFindingRecord]] = orm.relationship(
        back_populates="evaluation",
        cascade="all, delete-orphan",
        order_by="QaFindingRecord.ordinal",
        lazy="select",
    )


class QaFindingRecord(Base):
    """SQLAlchemy model for one finding belonging to an evaluation."""

    __tablename__ = "qa_findings"
    __table_args__ = (
        sa.UniqueConstraint(
            "evaluation_id",
            "ordinal",
            name="uq_qa_findings_evaluation_ordinal",
        ),
        sa.CheckConstraint(
            "ordinal >= 0",
            name="ck_qa_findings_ordinal_non_negative",
        ),
    )

    id: orm.Mapped[uuid.UUID] = orm.mapped_column(
        postgresql.UUID(as_uuid=True),
        primary_key=True,
    )
    evaluation_id: orm.Mapped[uuid.UUID] = orm.mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("qa_evaluations.id", ondelete="CASCADE"),
        nullable=False,
    )
    ordinal: orm.Mapped[int] = orm.mapped_column(sa.Integer, nullable=False)
    severity: orm.Mapped[QaFindingSeverity] = orm.mapped_column(
        QA_FINDING_SEVERITY,
        nullable=False,
    )
    code: orm.Mapped[str] = orm.mapped_column(sa.Text, nullable=False)
    summary: orm.Mapped[str] = orm.mapped_column(sa.Text, nullable=False)
    remediation: orm.Mapped[str] = orm.mapped_column(
        sa.Text,
        nullable=False,
        server_default="",
    )
    subject_id: orm.Mapped[str] = orm.mapped_column(
        sa.Text,
        nullable=False,
        server_default="",
    )
    subject_text: orm.Mapped[str] = orm.mapped_column(
        sa.Text,
        nullable=False,
        server_default="",
    )
    is_blocking: orm.Mapped[bool] = orm.mapped_column(sa.Boolean, nullable=False)
    citations: orm.Mapped[list[str]] = orm.mapped_column(
        postgresql.JSONB,
        nullable=False,
        server_default=_EMPTY_JSON_ARRAY,
    )
    details: orm.Mapped[JsonMapping] = orm.mapped_column(
        postgresql.JSONB,
        nullable=False,
        server_default=_EMPTY_JSON_OBJECT,
    )
    created_at: orm.Mapped[dt.datetime] = orm.mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )

    evaluation: orm.Mapped[QaEvaluationRecord] = orm.relationship(
        back_populates="findings",
    )
