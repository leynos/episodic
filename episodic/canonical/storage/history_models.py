"""History SQLAlchemy ORM models for canonical content."""

import datetime as dt  # noqa: TC003  # SQLAlchemy evaluates annotations at runtime.
import uuid  # noqa: TC003  # SQLAlchemy evaluates annotations at runtime.

import sqlalchemy as sa
from sqlalchemy import orm
from sqlalchemy.dialects import postgresql

from episodic.canonical.constraints import (
    UQ_EPISODE_TEMPLATE_HISTORY_REVISION,
    UQ_SERIES_PROFILE_HISTORY_REVISION,
)

from .models_base import Base


class SeriesProfileHistoryRecord(Base):
    """SQLAlchemy model for immutable series profile history entries.

    Attributes
    ----------
    id : uuid.UUID
        Primary key for the history entry.
    series_profile_id : uuid.UUID
        Foreign key to the series profile.
    revision : int
        Monotonically increasing revision number.
    actor : str | None
        Optional identifier for the actor who made the change.
    note : str | None
        Optional free-form note describing the change.
    snapshot : dict[str, object]
        JSONB snapshot of the profile state at this revision.
    created_at : datetime.datetime
        Timestamp when the history entry was created.
    """

    __tablename__ = "series_profile_history"

    id: orm.Mapped[uuid.UUID] = orm.mapped_column(
        postgresql.UUID(as_uuid=True),
        primary_key=True,
    )
    series_profile_id: orm.Mapped[uuid.UUID] = orm.mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("series_profiles.id"),
        nullable=False,
        index=True,
    )
    revision: orm.Mapped[int] = orm.mapped_column(sa.Integer, nullable=False)
    actor: orm.Mapped[str | None] = orm.mapped_column(sa.String(200), nullable=True)
    note: orm.Mapped[str | None] = orm.mapped_column(sa.Text, nullable=True)
    snapshot: orm.Mapped[dict[str, object]] = orm.mapped_column(
        postgresql.JSONB,
        nullable=False,
    )
    created_at: orm.Mapped[dt.datetime] = orm.mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )

    __table_args__ = (
        sa.UniqueConstraint(
            "series_profile_id",
            "revision",
            name=UQ_SERIES_PROFILE_HISTORY_REVISION,
        ),
    )


class EpisodeTemplateHistoryRecord(Base):
    """SQLAlchemy model for immutable episode template history entries.

    Attributes
    ----------
    id : uuid.UUID
        Primary key for the history entry.
    episode_template_id : uuid.UUID
        Foreign key to the episode template.
    revision : int
        Monotonically increasing revision number.
    actor : str | None
        Optional identifier for the actor who made the change.
    note : str | None
        Optional free-form note describing the change.
    snapshot : dict[str, object]
        JSONB snapshot of the template state at this revision.
    created_at : datetime.datetime
        Timestamp when the history entry was created.
    """

    __tablename__ = "episode_template_history"

    id: orm.Mapped[uuid.UUID] = orm.mapped_column(
        postgresql.UUID(as_uuid=True),
        primary_key=True,
    )
    episode_template_id: orm.Mapped[uuid.UUID] = orm.mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("episode_templates.id"),
        nullable=False,
        index=True,
    )
    revision: orm.Mapped[int] = orm.mapped_column(sa.Integer, nullable=False)
    actor: orm.Mapped[str | None] = orm.mapped_column(sa.String(200), nullable=True)
    note: orm.Mapped[str | None] = orm.mapped_column(sa.Text, nullable=True)
    snapshot: orm.Mapped[dict[str, object]] = orm.mapped_column(
        postgresql.JSONB,
        nullable=False,
    )
    created_at: orm.Mapped[dt.datetime] = orm.mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )

    __table_args__ = (
        sa.UniqueConstraint(
            "episode_template_id",
            "revision",
            name=UQ_EPISODE_TEMPLATE_HISTORY_REVISION,
        ),
    )
