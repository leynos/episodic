"""Write detection for a SQLAlchemy session, for unit-of-work commit safety.

The unit of work deliberately does not commit on exit (Risk 4). That makes
"did this scope leave work behind?" a question worth answering precisely, and
the obvious answer is wrong: ``Session.new`` is emptied by every flush, and a
core ``UPDATE`` or ``DELETE`` issued through ``Session.execute`` never
populates ``.new``, ``.dirty`` or ``.deleted`` in the first place. Both shapes
occur in the canonical adapters, so a check built on those collections is
silent on exactly the writes it exists to catch.

This tracker answers the same question from the two events that a write must
pass through regardless of shape: ``before_flush`` for ORM-staged changes, and
``do_orm_execute`` for statements executed directly.
"""

import typing as typ

from sqlalchemy import event

if typ.TYPE_CHECKING:
    from sqlalchemy.orm import ORMExecuteState, Session


class SessionWriteTracker:
    """Record whether a session has staged or executed any write.

    Attach one tracker per unit-of-work session. A read, a nested transaction
    boundary, and a flush with nothing pending all leave the tracker clean; an
    insert, update or delete of either shape marks it written.

    Parameters
    ----------
    session : sqlalchemy.orm.Session
        Synchronous session to observe. Pass ``AsyncSession.sync_session``
        when the caller holds an async session.

    Examples
    --------
    >>> tracker = SessionWriteTracker(session)
    >>> tracker.wrote
    False
    >>> tracker.mark_clean()
    """

    def __init__(self, session: Session) -> None:
        self._session = session
        self._wrote = False
        event.listen(session, "before_flush", self._on_flush)
        event.listen(session, "do_orm_execute", self._on_execute)

    @property
    def wrote(self) -> bool:
        """Whether a write has been staged or executed since the last clear."""
        return self._wrote

    def mark_clean(self) -> None:
        """Clear the flag after the session has been settled.

        Called once the session's work has been committed or rolled back, so
        the flag describes only what is still unsettled at exit.
        """
        self._wrote = False

    def _on_flush(self, *_args: object) -> None:
        """Mark the session written when the ORM flushes staged changes."""
        self._wrote = True

    def _on_execute(self, state: ORMExecuteState) -> None:
        """Mark the session written when a statement mutates rows.

        ``orm_execute_state`` covers statements that bypass the unit of work
        entirely, which is how the compare-and-set transitions persist.
        """
        if any((state.is_insert, state.is_update, state.is_delete)):
            self._wrote = True
