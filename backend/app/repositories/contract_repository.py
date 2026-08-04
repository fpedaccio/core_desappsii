"""Acceso a datos del catalogo de eventos y del registry de integracion."""

from __future__ import annotations

import uuid

from sqlalchemy import or_, select
from sqlalchemy.orm import joinedload, selectinload

from app.models.contracts import (
    EventContractVersion,
    EventType,
    EventTypeStatus,
    Producer,
    RegisteredModule,
    Subscription,
)
from app.repositories.base import BaseRepository, Page


class EventTypeRepository(BaseRepository[EventType]):
    model = EventType

    def _with_versions(self):
        return select(EventType).options(selectinload(EventType.versions))

    async def get_with_versions(self, event_type_id: uuid.UUID) -> EventType | None:
        stmt = self._with_versions().where(EventType.id == event_type_id)
        return (await self.session.execute(stmt)).scalars().first()

    async def get_by_name(self, name: str) -> EventType | None:
        stmt = self._with_versions().where(EventType.name == name)
        return (await self.session.execute(stmt)).scalars().first()

    async def search(
        self,
        *,
        query: str | None = None,
        owner_module: str | None = None,
        status: EventTypeStatus | None = None,
        page: int = 1,
        size: int = 20,
    ) -> Page[EventType]:
        stmt = self._with_versions()
        if query:
            pattern = f"%{query.lower().strip()}%"
            stmt = stmt.where(
                or_(EventType.name.ilike(pattern), EventType.description.ilike(pattern))
            )
        if owner_module:
            stmt = stmt.where(EventType.owner_module == owner_module)
        if status:
            stmt = stmt.where(EventType.status == status)
        return await self.paginate(stmt.order_by(EventType.name), page=page, size=size)

    async def list_all_with_versions(self) -> list[EventType]:
        """Usado para generar la documentacion del catalogo."""
        stmt = self._with_versions().order_by(EventType.owner_module, EventType.name)
        return list((await self.session.execute(stmt)).scalars().unique().all())


class ContractVersionRepository(BaseRepository[EventContractVersion]):
    model = EventContractVersion

    async def get_version(
        self, event_type_id: uuid.UUID, version: str
    ) -> EventContractVersion | None:
        return await self.find_one(event_type_id=event_type_id, version=version)

    async def list_for_type(self, event_type_id: uuid.UUID) -> list[EventContractVersion]:
        stmt = (
            select(EventContractVersion)
            .where(EventContractVersion.event_type_id == event_type_id)
            .order_by(EventContractVersion.created_at)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def latest_published(self, event_type_id: uuid.UUID) -> EventContractVersion | None:
        stmt = (
            select(EventContractVersion)
            .where(
                EventContractVersion.event_type_id == event_type_id,
                EventContractVersion.published_at.is_not(None),
                EventContractVersion.deprecated_at.is_(None),
            )
            .order_by(EventContractVersion.published_at.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalars().first()


class ModuleRepository(BaseRepository[RegisteredModule]):
    model = RegisteredModule

    async def get_by_name(self, name: str) -> RegisteredModule | None:
        return await self.find_one(name=name)

    async def list_active(self) -> list[RegisteredModule]:
        stmt = (
            select(RegisteredModule)
            .where(RegisteredModule.active.is_(True))
            .order_by(RegisteredModule.name)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_ordered(self) -> list[RegisteredModule]:
        stmt = select(RegisteredModule).order_by(RegisteredModule.name)
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_with_health_url(self) -> list[RegisteredModule]:
        stmt = select(RegisteredModule).where(
            RegisteredModule.active.is_(True), RegisteredModule.health_url.is_not(None)
        )
        return list((await self.session.execute(stmt)).scalars().all())


class ProducerRepository(BaseRepository[Producer]):
    model = Producer

    async def list_for_module(self, module_id: uuid.UUID) -> list[Producer]:
        stmt = (
            select(Producer)
            .options(joinedload(Producer.event_type))
            .where(Producer.module_id == module_id)
        )
        return list((await self.session.execute(stmt)).scalars().unique().all())

    async def list_all(self) -> list[Producer]:  # type: ignore[override]
        stmt = select(Producer).options(
            joinedload(Producer.event_type), joinedload(Producer.module)
        )
        return list((await self.session.execute(stmt)).scalars().unique().all())

    async def find_pair(self, module_id: uuid.UUID, event_type_id: uuid.UUID) -> Producer | None:
        return await self.find_one(module_id=module_id, event_type_id=event_type_id)


class SubscriptionRepository(BaseRepository[Subscription]):
    model = Subscription

    def _loaded(self):
        return select(Subscription).options(
            joinedload(Subscription.module), joinedload(Subscription.event_type)
        )

    async def active_for_event_type(self, event_type_name: str) -> list[Subscription]:
        """Las suscripciones que gobiernan el ruteo de un evento.

        Solo activas y de modulos activos: si un equipo dio de baja su modulo,
        el hub deja de entregarle sin que haya que tocar la topologia.
        """
        stmt = (
            self._loaded()
            .join(Subscription.event_type)
            .join(Subscription.module)
            .where(
                EventType.name == event_type_name,
                Subscription.active.is_(True),
                RegisteredModule.active.is_(True),
            )
        )
        return list((await self.session.execute(stmt)).scalars().unique().all())

    async def list_for_module(self, module_id: uuid.UUID) -> list[Subscription]:
        stmt = self._loaded().where(Subscription.module_id == module_id)
        return list((await self.session.execute(stmt)).scalars().unique().all())

    async def list_all(self) -> list[Subscription]:  # type: ignore[override]
        stmt = self._loaded().order_by(Subscription.created_at)
        return list((await self.session.execute(stmt)).scalars().unique().all())

    async def find_pair(
        self, module_id: uuid.UUID, event_type_id: uuid.UUID
    ) -> Subscription | None:
        return await self.find_one(module_id=module_id, event_type_id=event_type_id)

    async def active_queue_names(self) -> list[str]:
        """Colas que el Core tiene que declarar y bindear en el broker."""
        subscriptions = await self.list_all()
        return sorted(
            {
                sub.target_queue
                for sub in subscriptions
                if sub.active and sub.module.active
            }
        )
