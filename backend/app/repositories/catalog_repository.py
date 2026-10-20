"""Acceso a datos de los catalogos globales: zonas, barrios y listas de referencia."""

from __future__ import annotations

from sqlalchemy import func, select

from app.models.catalog import Barrio, ItemDeCatalogo, Zona
from app.repositories.base import BaseRepository


class ZonaRepository(BaseRepository[Zona]):
    model = Zona

    async def get_by_codigo(self, codigo: str) -> Zona | None:
        return await self.find_one(codigo=codigo.strip().lower())

    async def list_ordered(self, *, solo_activas: bool = False) -> list[Zona]:
        stmt = select(Zona).order_by(Zona.nombre)
        if solo_activas:
            stmt = stmt.where(Zona.activo.is_(True))
        return list((await self.session.execute(stmt)).scalars().unique().all())


class BarrioRepository(BaseRepository[Barrio]):
    model = Barrio

    async def get_by_codigo(self, codigo: str) -> Barrio | None:
        return await self.find_one(codigo=codigo.strip().lower())

    async def list_ordered(
        self,
        *,
        zona_codigo: str | None = None,
        texto: str | None = None,
        solo_activos: bool = False,
    ) -> list[Barrio]:
        stmt = select(Barrio).order_by(Barrio.nombre)
        if solo_activos:
            stmt = stmt.where(Barrio.activo.is_(True))
        if zona_codigo:
            stmt = stmt.join(Zona, Barrio.zona_id == Zona.id).where(
                Zona.codigo == zona_codigo.strip().lower()
            )
        if texto:
            # Busqueda por nombre sin distinguir mayusculas, que es como la va a
            # usar un buscador del frontend.
            stmt = stmt.where(func.lower(Barrio.nombre).contains(texto.strip().lower()))
        return list((await self.session.execute(stmt)).scalars().unique().all())


class ItemDeCatalogoRepository(BaseRepository[ItemDeCatalogo]):
    model = ItemDeCatalogo

    async def get_by_codigo(self, catalogo: str, codigo: str) -> ItemDeCatalogo | None:
        return await self.find_one(catalogo=catalogo.strip().lower(), codigo=codigo.strip().lower())

    async def list_items(
        self, catalogo: str, *, solo_activos: bool = False
    ) -> list[ItemDeCatalogo]:
        stmt = (
            select(ItemDeCatalogo)
            .where(ItemDeCatalogo.catalogo == catalogo.strip().lower())
            .order_by(ItemDeCatalogo.orden, ItemDeCatalogo.nombre)
        )
        if solo_activos:
            stmt = stmt.where(ItemDeCatalogo.activo.is_(True))
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_catalogos(self) -> list[str]:
        """Los nombres de catalogo que existen hoy, con cuantos items tiene cada uno."""
        stmt = (
            select(ItemDeCatalogo.catalogo)
            .group_by(ItemDeCatalogo.catalogo)
            .order_by(ItemDeCatalogo.catalogo)
        )
        return list((await self.session.execute(stmt)).scalars().all())
