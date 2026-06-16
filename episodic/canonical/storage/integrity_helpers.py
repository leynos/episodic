"""Storage-side helpers for translating ORM integrity errors to domain errors.

These helpers stay private to the storage package so domain modules do not see
SQLAlchemy types. Repositories call into them at the persistence boundary to
inspect ``IntegrityError`` instances and decide whether the failure represents a
known domain conflict that should be translated, or an unexpected violation
that should propagate unchanged.
"""

import typing as typ

from sqlalchemy.exc import IntegrityError

from episodic.canonical.constraints import REVISION_CONSTRAINT_NAMES

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from sqlalchemy.ext.asyncio import AsyncSession


def constraint_name(exc: BaseException) -> str | None:
    """Return the Postgres constraint name when the exception exposes one.

    Inspects the SQLAlchemy ``IntegrityError`` and its wrapped DB-API ``orig``
    exception, including each candidate's ``diag.constraint_name``. Returns
    ``None`` when no candidate reports a constraint name.
    """

    def _from_candidate(candidate: object | None) -> str | None:
        if candidate is None:
            return None
        direct = getattr(candidate, "constraint_name", None)
        if direct is not None:
            return typ.cast("str", direct)
        diag = getattr(candidate, "diag", None)
        name = getattr(diag, "constraint_name", None)
        return None if name is None else typ.cast("str", name)

    for candidate in (exc, getattr(exc, "orig", None)):
        name = _from_candidate(candidate)
        if name is not None:
            return name
    return None


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
    # Last-resort fallback for drivers that do not report a constraint name.
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


async def insert_with_conflict_translation(
    session: AsyncSession,
    record: object,
    *,
    translate: cabc.Callable[[IntegrityError], BaseException | None],
) -> None:
    """Insert ``record`` in a savepoint, translating recognised conflicts.

    The record is added inside a nested transaction and flushed immediately so
    constraint violations surface here rather than at the outer commit, leaving
    the caller's transaction intact for unrecognised failures. On
    ``IntegrityError`` the ``translate`` callback decides the outcome: returning
    a domain exception raises it chained from the original error, while
    returning ``None`` re-raises the original ``IntegrityError`` unchanged.

    Centralising the savepoint/flush/translate dance keeps every repository's
    conflict handling consistent and avoids repeating the boilerplate per
    ``add`` method.
    """
    try:
        async with session.begin_nested():
            session.add(record)
            await session.flush()
    except IntegrityError as exc:
        translated = translate(exc)
        if translated is None:
            raise
        raise translated from exc


async def add_translating_constraint_conflicts(
    session: AsyncSession,
    record: object,
    *,
    constraints: cabc.Container[str],
    on_conflict: cabc.Callable[[], BaseException],
) -> None:
    """Insert ``record``, translating known constraint violations to a domain error.

    A convenience wrapper over :func:`insert_with_conflict_translation` for the
    common case where a fixed set of named constraints maps to a single domain
    exception. When the violated constraint is in ``constraints`` the exception
    built by ``on_conflict`` is raised (chained from the original); any other
    ``IntegrityError`` propagates unchanged.
    """

    def _translate(exc: IntegrityError) -> BaseException | None:
        name = constraint_name(exc)
        if name is not None and name in constraints:
            return on_conflict()
        return None

    await insert_with_conflict_translation(session, record, translate=_translate)
