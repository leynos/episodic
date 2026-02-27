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

import typing as typ

from episodic.canonical.ports import CanonicalUnitOfWork
from episodic.logging import get_logger, log_info

from .repositories import (
    SqlAlchemyApprovalEventRepository,
    SqlAlchemyEpisodeRepository,
    SqlAlchemyEpisodeTemplateHistoryRepository,
    SqlAlchemyEpisodeTemplateRepository,
    SqlAlchemyIngestionJobRepository,
    SqlAlchemySeriesProfileHistoryRepository,
    SqlAlchemySeriesProfileRepository,
    SqlAlchemySourceDocumentRepository,
    SqlAlchemyTeiHeaderRepository,
)

if typ.TYPE_CHECKING:
    import collections.abc as cabc
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
    episode_templates : SqlAlchemyEpisodeTemplateRepository
        Repository for episode template persistence.
    series_profile_history : SqlAlchemySeriesProfileHistoryRepository
        Repository for series profile change history.
    episode_template_history : SqlAlchemyEpisodeTemplateHistoryRepository
        Repository for episode template change history.
    """

    def __init__(self, session_factory: cabc.Callable[[], AsyncSession]) -> None:
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
        self.episode_templates = SqlAlchemyEpisodeTemplateRepository(self._session)
        self.series_profile_history = SqlAlchemySeriesProfileHistoryRepository(
            self._session
        )
        self.episode_template_history = SqlAlchemyEpisodeTemplateHistoryRepository(
            self._session
        )
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
        try:
            if exc is not None:
                await self._session.rollback()
        finally:
            await self._session.close()

    def _require_session(self) -> AsyncSession:
        """Return the active session or raise when missing."""
        if self._session is None:
            msg = "Session not initialized for unit of work."
            raise RuntimeError(msg)
        return self._session

    async def _apply_session_action(self, action: str) -> None:
        """Apply a named action on the active session."""
        session = self._require_session()
        await getattr(session, action)()

    async def commit(self) -> None:
        """Commit the current unit-of-work transaction.

        Returns
        -------
        None

        Raises
        ------
        RuntimeError
            If no session has been initialized for the unit of work.
        """
        await self._apply_session_action("commit")
        log_info(logger, "Committed canonical unit of work.")

    async def flush(self) -> None:
        """Flush pending unit-of-work changes."""
        await self._require_session().flush()

    async def rollback(self) -> None:
        """Roll back the current unit-of-work session."""
        session = self._require_session()
        await session.rollback()
