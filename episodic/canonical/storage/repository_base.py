"""Shared SQLAlchemy repository primitives for canonical persistence."""

import dataclasses as dc
import typing as typ

import sqlalchemy as sa

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from sqlalchemy.ext.asyncio import AsyncSession


@dc.dataclass(slots=True)
class _RepositoryBase:
    """Shared helpers for SQLAlchemy repositories."""

    _session: AsyncSession

    async def _get_one_or_none[RecordT, DomainT](
        self,
        record_type: type[RecordT],
        where_clause: typ.Any,  # noqa: ANN401  # TODO(@codex): https://github.com/leynos/episodic/pull/14 - SQLAlchemy clause typing.
        mapper: cabc.Callable[[RecordT], DomainT],
    ) -> DomainT | None:
        """Return a mapped record for the query or None."""
        result = await self._session.execute(sa.select(record_type).where(where_clause))
        record = result.scalar_one_or_none()
        if record is None:
            return None
        return mapper(record)

    async def _get_many[RecordT, DomainT](
        self,
        record_type: type[RecordT],
        where_clause: typ.Any,  # noqa: ANN401  # TODO(@codex): https://github.com/leynos/episodic/pull/14 - SQLAlchemy clause typing.
        mapper: cabc.Callable[[RecordT], DomainT],
    ) -> list[DomainT]:
        """Return mapped records matching the query."""
        result = await self._session.execute(sa.select(record_type).where(where_clause))
        return [mapper(row) for row in result.scalars()]

    async def _add_record[RecordT](self, record: RecordT) -> None:
        """Add a record to the current SQLAlchemy session."""
        self._session.add(record)

    async def _list_where[RecordT, DomainT](
        self,
        record_type: type[RecordT],
        where_clause: typ.Any,  # noqa: ANN401  # TODO(@codex): https://github.com/leynos/episodic/pull/14 - SQLAlchemy clause typing.
        order_by_clause: typ.Any,  # noqa: ANN401  # TODO(@codex): https://github.com/leynos/episodic/pull/14 - SQLAlchemy clause typing.
        mapper: cabc.Callable[[RecordT], DomainT],
    ) -> list[DomainT]:
        """List mapped records matching a filter and ordering."""
        result = await self._session.execute(
            sa.select(record_type).where(where_clause).order_by(order_by_clause)
        )
        return [mapper(row) for row in result.scalars()]

    async def _get_latest_where[RecordT, DomainT](
        self,
        record_type: type[RecordT],
        where_clause: typ.Any,  # noqa: ANN401  # TODO(@codex): https://github.com/leynos/episodic/pull/14 - SQLAlchemy clause typing.
        order_by_desc_clause: typ.Any,  # noqa: ANN401  # TODO(@codex): https://github.com/leynos/episodic/pull/14 - SQLAlchemy clause typing.
        mapper: cabc.Callable[[RecordT], DomainT],
    ) -> DomainT | None:
        """Return the latest mapped record matching a filter."""
        result = await self._session.execute(
            sa
            .select(record_type)
            .where(where_clause)
            .order_by(order_by_desc_clause)
            .limit(1)
        )
        record = result.scalar_one_or_none()
        if record is None:
            return None
        return mapper(record)

    async def _update_where(
        self,
        record_type: type[object],
        where_clause: typ.Any,  # noqa: ANN401  # TODO(@codex): https://github.com/leynos/episodic/pull/14 - SQLAlchemy clause typing.
        values: dict[str, typ.Any],
    ) -> None:
        """Execute an update statement for matching records."""
        await self._session.execute(
            sa.update(record_type).where(where_clause).values(**values)
        )

    async def _update_entity_fields[EntityT](
        self,
        record_type: type[object],
        entity: EntityT,
        field_names: cabc.Sequence[str],
    ) -> None:
        """Update entity fields using the entity's current attribute values."""
        values = {field: getattr(entity, field) for field in field_names}
        id_field_name = "id"
        entity_id = getattr(entity, id_field_name)
        id_field = getattr(record_type, id_field_name)
        await self._update_where(record_type, id_field == entity_id, values)
