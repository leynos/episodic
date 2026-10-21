"""Shared schema constants for durable generation-run storage.

The expired-lease index is declared twice: once in the Alembic migration that
creates it and once in ``GenerationRunRecord.__table_args__``. Both import the
values below rather than repeating a literal, so the SQL predicate cannot drift
from the value the ORM mirrors -- drift that ``make check-migrations`` would not
catch, because Alembic's autogenerate does not compare partial-index predicates.
"""

from episodic.canonical.domain import GenerationRunStatus

GENERATION_RUN_EXPIRED_LEASE_INDEX = "ix_generation_runs_expired_lease"
GENERATION_RUN_RUNNING_STATUS = GenerationRunStatus.RUNNING.value
# Partial index predicate: only a running run can hold a live execution lease.
GENERATION_RUN_EXPIRED_LEASE_PREDICATE_SQL = (
    f"status = '{GENERATION_RUN_RUNNING_STATUS}'"
)

__all__ = (
    "GENERATION_RUN_EXPIRED_LEASE_INDEX",
    "GENERATION_RUN_EXPIRED_LEASE_PREDICATE_SQL",
    "GENERATION_RUN_RUNNING_STATUS",
)
