"""Storage-side helpers for translating ORM integrity errors to domain errors.

These helpers stay private to the storage package so domain modules do not see
SQLAlchemy types. Repositories call into them at the persistence boundary to
inspect ``IntegrityError`` instances and decide whether the failure represents a
known domain conflict that should be translated, or an unexpected violation
that should propagate unchanged.
"""

import typing as typ

from episodic.canonical.constraints import REVISION_CONSTRAINT_NAMES

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from sqlalchemy.exc import IntegrityError


def _exception_chain(exc: object) -> cabc.Iterator[object]:
    """Yield ``exc`` and its chained causes/contexts, then ``orig``, de-duplicated.

    The chain follows ``__cause__`` first, then ``__context__``, beginning with
    both the exception itself and any DB-API ``orig`` it carries so callers can
    reach the driver-level error regardless of how the chain was raised.
    """
    seen: set[int] = set()
    roots = (exc, getattr(exc, "orig", exc))
    for root in roots:
        current: object | None = root
        while current is not None and id(current) not in seen:
            seen.add(id(current))
            yield current
            current = getattr(current, "__cause__", None) or getattr(
                current, "__context__", None
            )


def constraint_name(exc: BaseException) -> str | None:
    """Return the Postgres constraint name when the exception exposes one.

    Walks the exception chain so callers can recover the constraint name from
    SQLAlchemy ``IntegrityError`` instances, the wrapped DB-API ``orig``
    exception, or any chained cause/context. Returns ``None`` when no driver
    reports a constraint name.
    """
    for node in _exception_chain(exc):
        direct = getattr(node, "constraint_name", None)
        if direct is not None:
            return typ.cast("str", direct)

    orig_exc = getattr(exc, "orig", exc)
    diag = getattr(orig_exc, "diag", None)
    return typ.cast("str | None", getattr(diag, "constraint_name", None))


def is_revision_conflict_integrity_error(
    exc: IntegrityError,
    entity_id_field: str,
) -> bool:
    """Return ``True`` when ``exc`` indicates a history revision collision.

    Checks the extracted constraint name against the known revision-uniqueness
    constraints, and falls back to substring matching on the driver message for
    drivers that do not surface a constraint name. ``entity_id_field`` names the
    parent column (e.g. ``"series_profile_id"``) used to disambiguate generic
    error messages.
    """
    name = constraint_name(exc)
    if name in REVISION_CONSTRAINT_NAMES:
        return True
    orig_exc = getattr(exc, "orig", exc)
    detail = str(orig_exc)
    return any(
        marker in detail
        for marker in (
            *REVISION_CONSTRAINT_NAMES,
            f"({entity_id_field}, revision)",
            f"{entity_id_field}, revision",
        )
    )
