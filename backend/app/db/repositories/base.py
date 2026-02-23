"""
Base repository with common CRUD operations.
"""

from typing import Any, Generic, Optional, Sequence, Type, TypeVar

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database import Base, get_session

T = TypeVar("T", bound=Base)


class BaseRepository(Generic[T]):
    """Generic async repository for SQLAlchemy models."""

    def __init__(self, model: Type[T]):
        self.model = model

    async def get_by_id(self, id: Any) -> Optional[T]:
        """Get a single record by primary key."""
        async with get_session() as session:
            return await session.get(self.model, id)

    async def list(
        self,
        *,
        filters: dict[str, Any] | None = None,
        order_by: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> Sequence[T]:
        """List records with optional filters, ordering, and pagination."""
        async with get_session() as session:
            stmt = select(self.model)

            if filters:
                for key, value in filters.items():
                    if value is not None and hasattr(self.model, key):
                        stmt = stmt.where(getattr(self.model, key) == value)

            if order_by and hasattr(self.model, order_by.lstrip("-")):
                col_name = order_by.lstrip("-")
                col = getattr(self.model, col_name)
                stmt = stmt.order_by(col.desc() if order_by.startswith("-") else col)

            if offset:
                stmt = stmt.offset(offset)
            if limit:
                stmt = stmt.limit(limit)

            result = await session.execute(stmt)
            return result.scalars().all()

    async def count(self, filters: dict[str, Any] | None = None) -> int:
        """Count records matching filters."""
        async with get_session() as session:
            stmt = select(func.count()).select_from(self.model)
            if filters:
                for key, value in filters.items():
                    if value is not None and hasattr(self.model, key):
                        stmt = stmt.where(getattr(self.model, key) == value)
            result = await session.execute(stmt)
            return result.scalar_one()

    async def create(self, **kwargs: Any) -> T:
        """Create a new record."""
        async with get_session() as session:
            instance = self.model(**kwargs)
            session.add(instance)
            await session.flush()
            await session.refresh(instance)
            return instance

    async def update(self, id: Any, **kwargs: Any) -> Optional[T]:
        """Update an existing record by primary key."""
        async with get_session() as session:
            instance = await session.get(self.model, id)
            if instance is None:
                return None
            for key, value in kwargs.items():
                if hasattr(instance, key):
                    setattr(instance, key, value)
            await session.flush()
            await session.refresh(instance)
            return instance

    async def delete(self, id: Any) -> bool:
        """Delete a record by primary key. Returns True if deleted."""
        async with get_session() as session:
            instance = await session.get(self.model, id)
            if instance is None:
                return False
            await session.delete(instance)
            return True

    async def upsert(self, id: Any, **kwargs: Any) -> T:
        """Insert or update a record."""
        async with get_session() as session:
            instance = await session.get(self.model, id)
            if instance is None:
                # Set the primary key
                pk_name = self.model.__table__.primary_key.columns.keys()[0]
                kwargs[pk_name] = id
                instance = self.model(**kwargs)
                session.add(instance)
            else:
                for key, value in kwargs.items():
                    if hasattr(instance, key):
                        setattr(instance, key, value)
            await session.flush()
            await session.refresh(instance)
            return instance
