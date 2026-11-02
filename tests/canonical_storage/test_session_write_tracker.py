"""Write-detection coverage for :class:`SessionWriteTracker`.

The unit of work relies on this tracker to tell an unsettled write from an idle
session. A synchronous SQLite engine exercises the same session-event semantics
as the async PostgreSQL sessions the unit of work uses, without needing a
database server, so these cases stay cheap enough to run on every change.
"""

import typing as typ

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from episodic.canonical.storage.session_write_tracker import SessionWriteTracker

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from sqlalchemy.engine import Engine


class _Base(DeclarativeBase):
    """Declarative base for the tracker's throwaway table."""


class _Row(_Base):
    """Minimal mapped row, so the ORM path has something to stage."""

    __tablename__ = "tracker_probe"

    id: Mapped[int] = mapped_column(primary_key=True)
    value: Mapped[str] = mapped_column(sa.String(32))


@pytest.fixture
def engine() -> cabc.Generator[Engine]:
    """Yield an in-memory SQLite engine holding one empty table."""
    engine = sa.create_engine("sqlite://")
    _Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def session(engine: Engine) -> cabc.Generator[Session]:
    """Yield a session that is rolled back and closed after the test."""
    with Session(engine) as session:
        yield session


@pytest.fixture
def tracker(session: Session) -> SessionWriteTracker:
    """Yield a tracker attached to the test session."""
    return SessionWriteTracker(session)


def test_a_fresh_tracker_reports_no_writes(tracker: SessionWriteTracker) -> None:
    """A tracker that has observed nothing yet starts clean."""
    assert tracker.wrote is False, "a fresh tracker must not claim a write"


def test_reads_do_not_count_as_writes(
    session: Session,
    tracker: SessionWriteTracker,
) -> None:
    """Selecting rows leaves the tracker clean."""
    session.add(_Row(id=1, value="alpha"))
    session.commit()
    tracker.mark_clean()

    assert session.get(_Row, 1) is not None, "the fixture row must be readable"
    session.execute(sa.select(_Row)).scalars().all()

    assert tracker.wrote is False, "reading must not be mistaken for writing"


def test_a_flush_with_nothing_pending_does_not_count_as_a_write(
    session: Session,
    tracker: SessionWriteTracker,
) -> None:
    """A no-op flush leaves the tracker clean.

    This is the case that makes a flush-counting tracker unusable: adapters
    flush defensively, and a bare ``flush()`` on an idle session writes
    nothing.
    """
    session.flush()

    assert tracker.wrote is False, "an empty flush must not be reported as a write"


def test_an_orm_add_counts_as_a_write(
    session: Session,
    tracker: SessionWriteTracker,
) -> None:
    """Adding a row through the ORM marks the session written."""
    session.add(_Row(id=1, value="alpha"))
    session.flush()

    assert tracker.wrote is True, "a flushed insert must be reported as a write"


def test_a_core_update_counts_as_a_write(
    session: Session,
    tracker: SessionWriteTracker,
) -> None:
    """A core ``UPDATE`` marks the session written.

    This is the case that ``Session.new``/``.dirty``/``.deleted`` cannot see,
    and it is how the compare-and-set transitions persist.
    """
    session.add(_Row(id=1, value="alpha"))
    session.commit()
    tracker.mark_clean()

    session.execute(sa.update(_Row).where(_Row.id == 1).values(value="beta"))

    assert tracker.wrote is True, "a core UPDATE must be reported as a write"


def test_a_core_delete_counts_as_a_write(
    session: Session,
    tracker: SessionWriteTracker,
) -> None:
    """A core ``DELETE`` marks the session written."""
    session.add(_Row(id=1, value="alpha"))
    session.commit()
    tracker.mark_clean()

    session.execute(sa.delete(_Row).where(_Row.id == 1))

    assert tracker.wrote is True, "a core DELETE must be reported as a write"


def test_mark_clean_clears_the_flag(
    session: Session,
    tracker: SessionWriteTracker,
) -> None:
    """Clearing the tracker resets it, so a settled session reads as clean."""
    session.add(_Row(id=1, value="alpha"))
    session.flush()
    assert tracker.wrote is True, "precondition: the insert must be observed"

    tracker.mark_clean()

    assert tracker.wrote is False, "mark_clean must reset the tracked write"
