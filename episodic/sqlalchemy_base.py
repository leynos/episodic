"""Shared SQLAlchemy metadata base for persisted application models."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared metadata registry for canonical and cost-accounting models."""
