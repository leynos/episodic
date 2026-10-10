"""Name the pricing snapshot content-hash unique constraint.

Online migration validates catalog preconditions before issuing DDL. Offline
SQL performs the same checks when executed; neither path owns the transaction.
"""

import typing as typ

import sqlalchemy as sa
from alembic.util import CommandError
from sqlalchemy.dialects import postgresql

from alembic import context, op

if typ.TYPE_CHECKING:
    from sqlalchemy.engine import Connection

revision = "20261010_000013"
down_revision = "20260624_000012"
branch_labels = None
depends_on = None

_LEGACY_NAME = "pricing_snapshots_content_hash_key"
_CURRENT_NAME = "uq_pricing_snapshots_content_hash"
_CONSTRAINTS_SQL = """
    SELECT c.conname, c.contype, ARRAY(
        SELECT a.attname::text FROM pg_attribute AS a
        WHERE a.attrelid = c.conrelid AND a.attnum = ANY(c.conkey)
        ORDER BY a.attnum
    ) AS column_names
    FROM pg_constraint AS c
    WHERE c.conrelid = to_regclass('pricing_snapshots')
      AND c.conname IN (:source_name, :target_name)
"""


def _offline_statement(source_name: str, target_name: str) -> str:
    """Render guarded SQL with safely quoted constant names for offline use."""
    dialect = postgresql.dialect(paramstyle="named")
    catalog_query = str(
        sa
        .text(_CONSTRAINTS_SQL)
        .bindparams(
            source_name=source_name,
            target_name=target_name,
        )
        .compile(dialect=dialect, compile_kwargs={"literal_binds": True})
    )
    statement = sa.text(f"""
        DO $$
        DECLARE
            constraint_record record;
            matching_constraints integer := 0;
            actual_name text;
            is_valid boolean := true;
        BEGIN
            FOR constraint_record IN {catalog_query}
            LOOP
                matching_constraints := matching_constraints + 1;
                actual_name := constraint_record.conname;
                is_valid := is_valid
                    AND constraint_record.contype = 'u'
                    AND constraint_record.column_names = ARRAY['content_hash'];
            END LOOP;
            IF matching_constraints = 0 THEN
                RAISE EXCEPTION
                    'Pricing snapshot content-hash unique constraint is missing';
            ELSIF matching_constraints > 1 THEN
                RAISE EXCEPTION
                    'Pricing snapshot content-hash constraints are ambiguous';
            ELSIF NOT is_valid THEN
                RAISE EXCEPTION 'Pricing snapshot content-hash constraint is malformed';
            END IF;
            IF actual_name = :source_name THEN
                EXECUTE 'ALTER TABLE pricing_snapshots RENAME CONSTRAINT '
                    || quote_ident(:source_name) || ' TO ' || quote_ident(:target_name);
            END IF;
        END;
        $$;
    """).bindparams(source_name=source_name, target_name=target_name)
    return str(
        statement.compile(
            dialect=dialect,
            compile_kwargs={"literal_binds": True},
        )
    )


def _validated_constraint_name(
    connection: Connection,
    source_name: str,
    target_name: str,
) -> str:
    """Read the single valid content-hash uniqueness constraint's name.

    Returns
    -------
    str
        The source or target name of the table's unique content-hash constraint.

    Raises
    ------
    CommandError
        If the expected constraint is missing, ambiguous, or malformed.
    """
    constraints = connection.execute(
        sa.text(_CONSTRAINTS_SQL),
        {
            "source_name": source_name,
            "target_name": target_name,
        },
    ).all()
    if not constraints:
        msg = "Pricing snapshot content-hash unique constraint is missing"
        raise CommandError(msg)
    if len(constraints) != 1:
        msg = "Pricing snapshot content-hash constraints are ambiguous"
        raise CommandError(msg)
    name, kind, columns = constraints[0]
    if kind != "u" or columns != ["content_hash"]:
        msg = "Pricing snapshot content-hash constraint is malformed"
        raise CommandError(msg)
    return str(name)


def _rename_constraint(source_name: str, target_name: str) -> None:
    """Validate the table's exact uniqueness boundary before renaming it."""
    if context.is_offline_mode():
        op.execute(_offline_statement(source_name, target_name))
        return
    connection = op.get_bind()
    name = _validated_constraint_name(connection, source_name, target_name)
    if name == source_name:
        # Only known, validated names reach DDL; quote them as identifiers.
        quote = connection.dialect.identifier_preparer.quote
        op.execute(
            "ALTER TABLE pricing_snapshots RENAME CONSTRAINT "
            f"{quote(source_name)} TO {quote(target_name)}"
        )


def upgrade() -> None:
    """Rename deployed constraints while accepting already-named previews."""
    _rename_constraint(_LEGACY_NAME, _CURRENT_NAME)


def downgrade() -> None:
    """Restore the constraint name used by the historical revision."""
    _rename_constraint(_CURRENT_NAME, _LEGACY_NAME)
