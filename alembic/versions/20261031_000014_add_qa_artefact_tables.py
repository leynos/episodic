"""Add durable QA artefact and finding tables."""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20261031_000014"
down_revision = "20261010_000013"
branch_labels = None
depends_on = None

_QA_EVALUATOR_VALUES = (
    "pedante",
    "bromide",
    "chiltern",
    "anthem",
    "caesura",
    "chrono",
)
_QA_COMPLIANCE_STATUS_VALUES = (
    "compliant",
    "non_compliant",
    "not_applicable",
    "errored",
)
_QA_FINDING_SEVERITY_VALUES = ("low", "medium", "high", "critical")


def _enum(name: str, *values: str) -> postgresql.ENUM:
    """Return an existing-or-creatable PostgreSQL enum."""
    return postgresql.ENUM(*values, name=name, create_type=False)


def _create_enums() -> None:
    """Create QA artefact PostgreSQL enums."""
    _enum("qa_evaluator", *_QA_EVALUATOR_VALUES).create(
        op.get_bind(),
        checkfirst=True,
    )
    _enum("qa_compliance_status", *_QA_COMPLIANCE_STATUS_VALUES).create(
        op.get_bind(),
        checkfirst=True,
    )
    _enum("qa_finding_severity", *_QA_FINDING_SEVERITY_VALUES).create(
        op.get_bind(),
        checkfirst=True,
    )


def _drop_enums() -> None:
    """Drop QA artefact PostgreSQL enums.

    Enum types are dropped last: ``checkfirst`` checks existence, not
    dependency, so dropping one while a table still references it fails.
    """
    _enum("qa_finding_severity", *_QA_FINDING_SEVERITY_VALUES).drop(
        op.get_bind(),
        checkfirst=True,
    )
    _enum("qa_compliance_status", *_QA_COMPLIANCE_STATUS_VALUES).drop(
        op.get_bind(),
        checkfirst=True,
    )
    _enum("qa_evaluator", *_QA_EVALUATOR_VALUES).drop(
        op.get_bind(),
        checkfirst=True,
    )


def _create_qa_evaluations_table() -> None:
    """Create recorded evaluator invocations."""
    op.create_table(
        "qa_evaluations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "episode_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("episodes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "generation_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("generation_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "evaluator",
            _enum("qa_evaluator", *_QA_EVALUATOR_VALUES),
            nullable=False,
        ),
        sa.Column("evaluator_version", sa.Text(), nullable=False),
        sa.Column("artefact_schema_version", sa.Integer(), nullable=False),
        sa.Column("compliance_policy_version", sa.Integer(), nullable=False),
        sa.Column(
            "compliance_status",
            _enum("qa_compliance_status", *_QA_COMPLIANCE_STATUS_VALUES),
            nullable=False,
        ),
        sa.Column(
            "summary",
            sa.Text(),
            server_default=sa.text("''"),
            nullable=False,
        ),
        sa.Column("rubric_score", sa.Numeric(5, 4), nullable=True),
        sa.Column("runtime_estimate_seconds", sa.Integer(), nullable=True),
        sa.Column(
            "finding_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "evaluator_metadata",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
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
    )
    op.create_index(
        "ix_qa_evaluations_episode_evaluated_at",
        "qa_evaluations",
        ["episode_id", sa.text("evaluated_at DESC"), sa.text("id DESC")],
    )
    op.create_index(
        "ix_qa_evaluations_episode_evaluator_evaluated_at",
        "qa_evaluations",
        ["episode_id", "evaluator", sa.text("evaluated_at DESC"), sa.text("id DESC")],
    )
    # ``generation_runs`` deletes null this column, and the existing indexes
    # all lead with ``episode_id``, so without a partial index a purge scans
    # the whole table once per deleted run.
    op.create_index(
        "ix_qa_evaluations_generation_run_id",
        "qa_evaluations",
        ["generation_run_id"],
        postgresql_where=sa.text("generation_run_id IS NOT NULL"),
    )


def _drop_qa_evaluations_table() -> None:
    """Drop recorded evaluator invocations."""
    op.drop_index(
        "ix_qa_evaluations_generation_run_id",
        table_name="qa_evaluations",
    )
    op.drop_index(
        "ix_qa_evaluations_episode_evaluator_evaluated_at",
        table_name="qa_evaluations",
    )
    op.drop_index(
        "ix_qa_evaluations_episode_evaluated_at",
        table_name="qa_evaluations",
    )
    op.drop_table("qa_evaluations")


def _create_qa_findings_table() -> None:
    """Create findings belonging to recorded evaluations."""
    op.create_table(
        "qa_findings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "evaluation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("qa_evaluations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column(
            "severity",
            _enum("qa_finding_severity", *_QA_FINDING_SEVERITY_VALUES),
            nullable=False,
        ),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column(
            "remediation",
            sa.Text(),
            server_default=sa.text("''"),
            nullable=False,
        ),
        sa.Column(
            "subject_id",
            sa.Text(),
            server_default=sa.text("''"),
            nullable=False,
        ),
        sa.Column(
            "subject_text",
            sa.Text(),
            server_default=sa.text("''"),
            nullable=False,
        ),
        sa.Column("is_blocking", sa.Boolean(), nullable=False),
        sa.Column(
            "citations",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "details",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
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


def _drop_qa_findings_table() -> None:
    """Drop findings belonging to recorded evaluations."""
    op.drop_table("qa_findings")


def upgrade() -> None:
    """Create QA artefact persistence tables."""
    _create_enums()
    _create_qa_evaluations_table()
    _create_qa_findings_table()


def downgrade() -> None:
    """Drop QA artefact persistence tables."""
    _drop_qa_findings_table()
    _drop_qa_evaluations_table()
    _drop_enums()
