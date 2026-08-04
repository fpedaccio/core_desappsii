"""Acceso a datos de los catalogos globales."""

from __future__ import annotations

import uuid

from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload

from app.models.catalog import Barrio, CatalogItem, CatalogType, Dependencia, Zona
from app.repositories.base import BaseRepository, Page


class DependenciaRepository(BaseRepository[Dependencia]):
    model = Dependencia

    async def get_by_code(self, code: str) -> Dependencia | None:
        return await self.find_one(code=code)

    async def search(
        self, *, query: str | None = None, active: bool | None = None, page: int = 1, size: int = 20
    ) -> Page[Dependencia]:
        stmt = select(Dependencia)
        if query:
            pattern = f"%{query.lower().strip()}%"
            stmt = stmt.where(
                or_(Dependencia.name.ilike(pattern), Dependencia.code.ilike(pattern))
            )
        if active is not None:
            stmt = stmt.where(Dependencia.active.is_(active))
        return await self.paginate(stmt.order_by(Dependencia.name), page=page, size=size)


class ZonaRepository(BaseRepository[Zona]):
    model = Zona

    async def get_by_code(self, code: str) -> Zona | None:
        return await self.find_one(code=code)

    async def search(
        self, *, query: str | None = None, active: bool | None = None, page: int = 1, size: int = 20
    ) -> Page[Zona]:
        stmt = select(Zona)
        if query:
            pattern = f"%{query.lower().strip()}%"
            stmt = stmt.where(or_(Zona.name.ilike(pattern), Zona.code.ilike(pattern)))
        if active is not None:
            stmt = stmt.where(Zona.active.is_(active))
        return await self.paginate(stmt.order_by(Zona.name), page=page, size=size)


class BarrioRepository(BaseRepository[Barrio]):
    model = Barrio

    async def get_by_code(self, code: str) -> Barrio | None:
        return await self.find_one(code=code)

    async def search(
        self,
        *,
        query: str | None = None,
        zona_id: uuid.UUID | None = None,
        active: bool | None = None,
        page: int = 1,
        size: int = 20,
    ) -> Page[Barrio]:
        stmt = select(Barrio)
        if query:
            pattern = f"%{query.lower().strip()}%"
            stmt = stmt.where(
                or_(
                    Barrio.name.ilike(pattern),
                    Barrio.code.ilike(pattern),
                    Barrio.postal_code.ilike(pattern),
                )
            )
        if zona_id:
            stmt = stmt.where(Barrio.zona_id == zona_id)
        if active is not None:
            stmt = stmt.where(Barrio.active.is_(active))
        return await self.paginate(stmt.order_by(Barrio.name), page=page, size=size)


class CatalogTypeRepository(BaseRepository[CatalogType]):
    model = CatalogType

    async def get_by_code(self, code: str) -> CatalogType | None:
        return await self.find_one(code=code)

    async def get_with_items(self, code: str) -> CatalogType | None:
        stmt = (
            select(CatalogType)
            .options(selectinload(CatalogType.items))
            .where(CatalogType.code == code)
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def list_ordered(self) -> list[CatalogType]:
        stmt = select(CatalogType).order_by(CatalogType.code)
        return list((await self.session.execute(stmt)).scalars().all())


class CatalogItemRepository(BaseRepository[CatalogItem]):
    model = CatalogItem

    async def get_by_code(self, catalog_type_id: uuid.UUID, code: str) -> CatalogItem | None:
        return await self.find_one(catalog_type_id=catalog_type_id, code=code)

    async def search(
        self,
        *,
        catalog_type_id: uuid.UUID,
        query: str | None = None,
        active: bool | None = None,
        page: int = 1,
        size: int = 50,
    ) -> Page[CatalogItem]:
        stmt = select(CatalogItem).where(CatalogItem.catalog_type_id == catalog_type_id)
        if query:
            pattern = f"%{query.lower().strip()}%"
            stmt = stmt.where(
                or_(CatalogItem.label.ilike(pattern), CatalogItem.code.ilike(pattern))
            )
        if active is not None:
            stmt = stmt.where(CatalogItem.active.is_(active))
        return await self.paginate(
            stmt.order_by(CatalogItem.sort_order, CatalogItem.label), page=page, size=size
        )
