"""Profile and template SQLAlchemy ORM models for canonical content."""

import datetime as dt  # noqa: TC003  # SQLAlchemy evaluates annotations at runtime.
import uuid  # noqa: TC003  # SQLAlchemy evaluates annotations at runtime.

import sqlalchemy as sa
from sqlalchemy import orm
from sqlalchemy.dialects import postgresql

from .models_base import Base


class SeriesProfileRecord(Base):
    """SQLAlchemy model for series profiles.

    Attributes
    ----------
    id : uuid.UUID
        Primary key for the series profile.
    slug : str
        Unique human-friendly identifier for the series.
    title : str
        Display title for the series.
    description : str | None
        Optional description for the series.
    configuration : dict[str, object]
        Free-form configuration settings associated with the series.
    created_at : datetime.datetime
        Timestamp when the record was created.
    updated_at : datetime.datetime
        Timestamp when the record was last updated.
    """

    __tablename__ = "series_profiles"

    id: orm.Mapped[uuid.UUID] = orm.mapped_column(
        postgresql.UUID(as_uuid=True),
        primary_key=True,
    )
    slug: orm.Mapped[str] = orm.mapped_column(
        sa.String(160),
        nullable=False,
        unique=True,
    )
    title: orm.Mapped[str] = orm.mapped_column(sa.String(240), nullable=False)
    description: orm.Mapped[str | None] = orm.mapped_column(sa.Text, nullable=True)
    configuration: orm.Mapped[dict[str, object]] = orm.mapped_column(
        postgresql.JSONB,
        default=dict,
        nullable=False,
    )
    guardrails: orm.Mapped[dict[str, object]] = orm.mapped_column(
        postgresql.JSONB,
        default=dict,
        nullable=False,
    )
    created_at: orm.Mapped[dt.datetime] = orm.mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )
    updated_at: orm.Mapped[dt.datetime] = orm.mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )


class EpisodeTemplateRecord(Base):
    """SQLAlchemy model for episode templates.

    Attributes
    ----------
    id : uuid.UUID
        Primary key for the episode template.
    series_profile_id : uuid.UUID
        Foreign key to the owning series profile.
    slug : str
        Unique slug within a series profile namespace.
    title : str
        Human-readable episode template title.
    description : str | None
        Optional longer description of template purpose.
    structure : dict[str, object]
        JSON structure used to define template sections.
    created_at : datetime.datetime
        Timestamp when the record was created.
    updated_at : datetime.datetime
        Timestamp when the record was last updated.
    """

    __tablename__ = "episode_templates"

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
    slug: orm.Mapped[str] = orm.mapped_column(sa.String(160), nullable=False)
    title: orm.Mapped[str] = orm.mapped_column(sa.String(240), nullable=False)
    description: orm.Mapped[str | None] = orm.mapped_column(sa.Text, nullable=True)
    structure: orm.Mapped[dict[str, object]] = orm.mapped_column(
        postgresql.JSONB,
        default=dict,
        nullable=False,
    )
    guardrails: orm.Mapped[dict[str, object]] = orm.mapped_column(
        postgresql.JSONB,
        default=dict,
        nullable=False,
    )
    created_at: orm.Mapped[dt.datetime] = orm.mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
    )
    updated_at: orm.Mapped[dt.datetime] = orm.mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )

    __table_args__ = (
        sa.UniqueConstraint(
            "series_profile_id",
            "slug",
            name="uq_episode_templates_series_slug",
        ),
    )
