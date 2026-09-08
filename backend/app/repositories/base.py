"""Base de la capa de acceso a datos.

Los repositorios son el unico lugar del backend que construye queries. Los
servicios reciben repositorios, no sesiones, y por eso no pueden escribir SQL
ni saltarse esta capa.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import Base
from app.core.errors import NotFoundError

ModelT = TypeVar("ModelT", bound=Base)

MAX_PAGE_SIZE = 200


@dataclass(frozen=True)
class Page(Generic[ModelT]):
    """Resultado paginado. El FE usa `total` y `pages` para el paginador."""

    items: list[ModelT]
    total: int
    page: int
    size: int

    @property
    def pages(self) -> int:
        return math.ceil(self.total / self.size) if self.size else 0


class BaseRepository(Generic[ModelT]):
    model: type[ModelT]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # -- lectura -----------------------------------------------------------
    async def get(self, entity_id: uuid.UUID | str) -> ModelT | None:
        return await self.session.get(self.model, entity_id)

    async def get_required(self, entity_id: uuid.UUID | str) -> ModelT:
        """Igual que `get` pero levanta `NotFoundError` en vez de devolver None."""
        entity = await self.get(entity_id)
        if entity is None:
            raise NotFoundError(f"No existe {self.model.__name__} con id {entity_id}.")
        return entity

    async def find_one(self, **filters: Any) -> ModelT | None:
        stmt = select(self.model).filter_by(**filters).limit(1)
        return (await self.session.execute(stmt)).scalars().first()

    async def find_one_required(self, **filters: Any) -> ModelT:
        entity = await self.find_one(**filters)
        if entity is None:
            criteria = ", ".join(f"{key}={value!r}" for key, value in filters.items())
            raise NotFoundError(f"No existe {self.model.__name__} con {criteria}.")
        return entity

    async def exists(self, **filters: Any) -> bool:
        stmt = select(func.count()).select_from(self.model).filter_by(**filters)
        return bool((await self.session.execute(stmt)).scalar_one())

    async def list_all(self, **filters: Any) -> list[ModelT]:
        stmt = select(self.model)
        if filters:
            stmt = stmt.filter_by(**filters)
        return list((await self.session.execute(stmt)).scalars().all())

    async def paginate(self, stmt: Select, *, page: int = 1, size: int = 20) -> Page[ModelT]:
        page = max(page, 1)
        size = min(max(size, 1), MAX_PAGE_SIZE)

        # `order_by(None)` evita que el ORDER BY del listado rompa el COUNT.
        count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
        total = int((await self.session.execute(count_stmt)).scalar_one())

        result = await self.session.execute(stmt.limit(size).offset((page - 1) * size))
        items = list(result.scalars().unique().all())
        return Page(items=items, total=total, page=page, size=size)

    # -- escritura ---------------------------------------------------------
    def add(self, entity: ModelT) -> ModelT:
        self.session.add(entity)
        return entity

    async def delete(self, entity: ModelT) -> None:
        await self.session.delete(entity)

    async def flush(self) -> None:
        """Empuja los cambios para obtener ids y disparar constraints, sin cerrar
        la transaccion (el commit lo hace la dependencia de sesion)."""
        await self.session.flush()
