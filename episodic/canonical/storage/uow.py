"""Unit-of-work implementation for canonical persistence.

This module defines the async unit-of-work used by canonical content services
to coordinate repository access and transactional boundaries.

Examples
--------
Commit work in a single unit-of-work:

>>> async with SqlAlchemyUnitOfWork(session_factory) as uow:
...     await uow.episodes.add(episode)
...     await uow.commit()
"""

from __future__ import annotations

import typing as typ

from episodic.canonical.ports import CanonicalUnitOfWork
from episodic.logging import get_logger, log_info

from .repositories import (
    SqlAlchemyApprovalEventRepository,
    SqlAlchemyEpisodeRepository,
    SqlAlchemyIngestionJobRepository,
    SqlAlchemySeriesProfileRepository,
    SqlAlchemySourceDocumentRepository,
    SqlAlchemyTeiHeaderRepository,
)

if typ.TYPE_CHECKING:
    from types import TracebackType

    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)


class SqlAlchemyUnitOfWork(CanonicalUnitOfWork):
    """Async unit-of-work backed by SQLAlchemy sessions.

    Parameters
    ----------
    session_factory : collections.abc.Callable[[], AsyncSession]
        Factory that produces new async sessions for the unit-of-work scope.

    Attributes
    ----------
    series_profiles : SqlAlchemySeriesProfileRepository
        Repository for series profile persistence.
    tei_headers : SqlAlchemyTeiHeaderRepository
        Repository for TEI header persistence.
    episodes : SqlAlchemyEpisodeRepository
        Repository for canonical episode persistence.
    ingestion_jobs : SqlAlchemyIngestionJobRepository
        Repository for ingestion job persistence.
    source_documents : SqlAlchemySourceDocumentRepository
        Repository for source document persistence.
    approval_events : SqlAlchemyApprovalEventRepository
        Repository for approval event persistence.
    """

    def __init__(self, session_factory: typ.Callable[[], AsyncSession]) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None

    async def __aenter__(self) -> SqlAlchemyUnitOfWork:
        """Open a unit-of-work session.

        Returns
        -------
        SqlAlchemyUnitOfWork
            The active unit-of-work instance.
        """
        self._session = self._session_factory()
        self.series_profiles = SqlAlchemySeriesProfileRepository(self._session)
        self.tei_headers = SqlAlchemyTeiHeaderRepository(self._session)
        self.episodes = SqlAlchemyEpisodeRepository(self._session)
        self.ingestion_jobs = SqlAlchemyIngestionJobRepository(self._session)
        self.source_documents = SqlAlchemySourceDocumentRepository(self._session)
        self.approval_events = SqlAlchemyApprovalEventRepository(self._session)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close the unit-of-work session.

        Parameters
        ----------
        exc_type : type[BaseException] | None
            Exception type raised within the context, if any.
        exc : BaseException | None
            Exception instance raised within the context, if any.
        traceback : TracebackType | None
            Traceback for the raised exception, if any.

        Returns
        -------
        None
        """
        if self._session is None:
            return
        if exc is not None:
            await self._session.rollback()
        await self._session.close()

    async def commit(self) -> None:
        """Commit the current unit-of-work transaction.

        Returns
        -------
        None

        Raises
        ------
        RuntimeError
            If no session has been initialised for the unit of work.
        """
        if self._session is None:
            msg = "Session not initialised for unit of work."
            raise RuntimeError(msg)
        await self._session.commit()
        log_info(logger, "Committed canonical unit of work.")

    async def flush(self) -> None:
        """Flush pending unit-of-work changes.

        Returns
        -------
        None

        Raises
        ------
        RuntimeError
            If no session has been initialised for the unit of work.
        """
        if self._session is None:
            msg = "Session not initialised for unit of work."
            raise RuntimeError(msg)
        await self._session.flush()

    async def rollback(self) -> None:
        """Roll back the current unit-of-work session.

        Returns
        -------
        None

        Raises
        ------
        RuntimeError
            If no session has been initialised for the unit of work.
        """
        if self._session is None:
            msg = "Session not initialised for unit of work."
            raise RuntimeError(msg)
        await self._session.rollback()
