"""Add the QA-gated quality-mode and QA-status labels.

Online migration appends labels with ``ALTER TYPE ... ADD VALUE IF NOT
EXISTS`` and therefore issues no query that could use a new label in the same
transaction. Offline SQL emits the same guarded statements. Neither path owns
the transaction.

Downgrade refuses to run while any row still uses a new label, because
PostgreSQL cannot drop an enum label without recreating the type.
"""

import typing as typ

import sqlalchemy as sa
from alembic.util import CommandError
from sqlalchemy.dialects import postgresql

from alembic import context, op

if typ.TYPE_CHECKING:
    from sqlalchemy.engine import Connection

revision = "20261122_000018"
down_revision = "20261110_000017"
branch_labels = None
depends_on = None

_ORIGINAL_INPUT = "draft_without_qa"
_NEW_QUALITY_MODES: tuple[str, ...] = ("qa_gated",)
_ORIGINAL_QA_STATUS = "skipped"
_NEW_QA_STATUSES: tuple[str, ...] = ("pending", "passed", "failed")

_QA_STATUS_COLUMNS: tuple[tuple[str, str], ...] = (
    ("generation_runs", "qa_status"),
    ("episodes", "qa_status"),
)
_QUALITY_MODE_COLUMNS: tuple[tuple[str, str], ...] = (
    ("generation_runs", "quality_mode"),
)
_LABEL_USAGE_COLUMNS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("generation_runs", "qa_status", _NEW_QA_STATUSES),
    ("episodes", "qa_status", _NEW_QA_STATUSES),
    ("generation_runs", "quality_mode", _NEW_QUALITY_MODES),
)


def _new_label_usage_sql() -> str:
    """Return the query testing whether any row still uses a new label.

    Every interpolated component comes from this module's constants, never
    from user input, so the statement is safe to build as text.

    Returns
    -------
    str
        SQL returning a single boolean.
    """
    clauses = " OR ".join(
        f"EXISTS (SELECT 1 FROM {table} WHERE {column}::text IN "  # ruff: ignore[hardcoded-sql-expression]  # Constant names only.
        f"({', '.join(_quoted(values))}))"
        for table, column, values in _LABEL_USAGE_COLUMNS
    )
    return f"SELECT {clauses}"


def _quoted(values: tuple[str, ...]) -> tuple[str, ...]:
    """Quote literal enum labels for SQL that holds no user input."""
    return tuple(f"'{value}'" for value in values)


def _offline_downgrade_statement() -> str:
    """Render the offline guard that refuses a lossy downgrade."""
    usage_query = _new_label_usage_sql()
    return (
        "DO $$\n"
        "BEGIN\n"
        f"    IF ({usage_query}) THEN\n"
        "        RAISE EXCEPTION\n"
        "            'QA-gated quality-mode labels are still in use';\n"
        "    END IF;\n"
        "END;\n"
        "$$;"
    )


def _require_no_new_label_rows(connection: Connection) -> None:
    """Refuse a downgrade that would lose rows using a new label.

    Raises
    ------
    CommandError
        If any run or episode still uses a label this revision introduced.
    """
    is_in_use = connection.execute(sa.text(_new_label_usage_sql())).scalar()
    if is_in_use:
        msg = (
            "Cannot downgrade: rows still use the qa_gated quality mode or a "
            "pending, passed, or failed QA status."
        )
        raise CommandError(msg)


def _recreate_enum(
    connection: Connection,
    *,
    enum_name: str,
    original_value: str,
) -> None:
    """Recreate an enum with only its original label, preserving casts."""
    quote = connection.dialect.identifier_preparer.quote
    old_name = f"{enum_name}_old"
    op.execute(f"ALTER TYPE {quote(enum_name)} RENAME TO {quote(old_name)}")
    postgresql.ENUM(
        original_value,
        name=enum_name,
        create_type=False,
    ).create(connection, checkfirst=False)
    for table, column in _columns_for(enum_name):
        op.execute(
            f"ALTER TABLE {quote(table)} ALTER COLUMN {quote(column)} "
            f"TYPE {quote(enum_name)} USING {quote(column)}::text::"
            f"{quote(enum_name)}"
        )
    op.execute(f"DROP TYPE {quote(old_name)}")


def _columns_for(enum_name: str) -> tuple[tuple[str, str], ...]:
    """Return the ``(table, column)`` pairs that use an enum type."""
    if enum_name == "qa_status":
        return _QA_STATUS_COLUMNS
    return _QUALITY_MODE_COLUMNS


def upgrade() -> None:
    """Append the QA-gated labels without using them in this transaction."""
    op.execute("ALTER TYPE quality_mode ADD VALUE IF NOT EXISTS 'qa_gated'")
    for value in _NEW_QA_STATUSES:
        op.execute(f"ALTER TYPE qa_status ADD VALUE IF NOT EXISTS '{value}'")


def downgrade() -> None:
    """Restore the single-label enums, refusing to lose row data."""
    if context.is_offline_mode():
        op.execute(_offline_downgrade_statement())
    else:
        _require_no_new_label_rows(op.get_bind())
    connection = op.get_bind()
    _recreate_enum(
        connection,
        enum_name="qa_status",
        original_value=_ORIGINAL_QA_STATUS,
    )
    _recreate_enum(
        connection,
        enum_name="quality_mode",
        original_value=_ORIGINAL_INPUT,
    )
