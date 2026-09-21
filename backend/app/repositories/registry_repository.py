"""Acceso a datos de modulos, tipos de evento y suscripciones."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import joinedload

from app.models.registry import EventType, ModuleAccount, Publication, Subscription
from app.models.users import User
from app.repositories.base import BaseRepository, Page


class ModuleRepository(BaseRepository[ModuleAccount]):
    model = ModuleAccount

    async def get_by_name(self, name: str) -> ModuleAccount | None:
        return await self.find_one(name=name.strip().lower())

    async def list_ordered(self) -> list[ModuleAccount]:
        stmt = select(ModuleAccount).order_by(ModuleAccount.name)
        return list((await self.session.execute(stmt)).scalars().unique().all())

    async def list_active(self) -> list[ModuleAccount]:
        stmt = (
            select(ModuleAccount).where(ModuleAccount.active.is_(True)).order_by(ModuleAccount.name)
        )
        return list((await self.session.execute(stmt)).scalars().unique().all())


class EventTypeRepository(BaseRepository[EventType]):
    model = EventType

    async def get_by_name(self, name: str) -> EventType | None:
        return await self.find_one(name=name.strip())

    async def list_ordered(self) -> list[EventType]:
        stmt = select(EventType).order_by(EventType.name)
        return list((await self.session.execute(stmt)).scalars().all())

    async def search(
        self,
        *,
        query: str | None = None,
        owner_module: str | None = None,
        discovered: bool | None = None,
        page: int = 1,
        size: int = 50,
    ) -> Page[EventType]:
        stmt = select(EventType)
        if query:
            pattern = f"%{query.strip()}%"
            stmt = stmt.where(
                or_(EventType.name.ilike(pattern), EventType.description.ilike(pattern))
            )
        if owner_module:
            stmt = stmt.where(EventType.owner_module == owner_module)
        if discovered is not None:
            stmt = stmt.where(EventType.discovered.is_(discovered))
        return await self.paginate(stmt.order_by(EventType.name), page=page, size=size)

    async def get_or_create(
        self, name: str, *, source_module: str | None, seen_at: datetime
    ) -> tuple[EventType, bool]:
        """Devuelve el tipo, creandolo si es la primera vez que se ve.

        El auto-registro es lo que hace del Core un pasamanos de verdad: un tipo
        que nadie declaro no traba la integracion, aparece en el dashboard
        marcado como `discovered` para que los equipos lo acomoden.
        """
        existing = await self.get_by_name(name)
        if existing is not None:
            existing.last_seen_at = seen_at
            existing.total_received = (existing.total_received or 0) + 1
            if existing.first_seen_at is None:
                existing.first_seen_at = seen_at
            return existing, False

        event_type = EventType(
            name=name.strip(),
            owner_module=source_module,
            discovered=True,
            description="",
            json_schema=None,
            first_seen_at=seen_at,
            last_seen_at=seen_at,
            total_received=1,
        )
        self.add(event_type)
        await self.flush()
        return event_type, True


class SubscriptionRepository(BaseRepository[Subscription]):
    model = Subscription

    def _loaded(self):
        return select(Subscription).options(
            joinedload(Subscription.module), joinedload(Subscription.event_type)
        )

    async def active_for_event_type(self, event_type_name: str) -> list[Subscription]:
        """Las suscripciones que gobiernan el ruteo de un evento.

        Solo activas y de modulos activos: dar de baja un modulo deja de
        entregarle sin tocar la topologia ni sus suscripciones.
        """
        stmt = (
            self._loaded()
            .join(Subscription.event_type)
            .join(Subscription.module)
            .where(
                EventType.name == event_type_name,
                Subscription.active.is_(True),
                ModuleAccount.active.is_(True),
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

    async def subscriber_count(self, event_type_name: str) -> int:
        stmt = (
            select(func.count())
            .select_from(Subscription)
            .join(Subscription.event_type)
            .where(EventType.name == event_type_name, Subscription.active.is_(True))
        )
        return int((await self.session.execute(stmt)).scalar_one())

    async def active_queue_names(self) -> list[str]:
        """Colas que el Core tiene que declarar y bindear en el broker."""
        subs = await self.list_all()
        return sorted({s.target_queue for s in subs if s.active and s.module.active})

    async def counts_by_event_type(self) -> dict[str, int]:
        stmt = (
            select(EventType.name, func.count())
            .join(Subscription, Subscription.event_type_id == EventType.id)
            .where(Subscription.active.is_(True))
            .group_by(EventType.name)
        )
        return {name: int(total) for name, total in (await self.session.execute(stmt)).all()}


class PublicationRepository(BaseRepository[Publication]):
    model = Publication

    def _loaded(self):
        return select(Publication).options(
            joinedload(Publication.module), joinedload(Publication.event_type)
        )

    async def list_all(self) -> list[Publication]:  # type: ignore[override]
        stmt = self._loaded().order_by(Publication.created_at)
        return list((await self.session.execute(stmt)).scalars().unique().all())

    async def list_for_module(self, module_id: uuid.UUID) -> list[Publication]:
        stmt = self._loaded().where(Publication.module_id == module_id)
        return list((await self.session.execute(stmt)).scalars().unique().all())

    async def find_pair(self, module_id: uuid.UUID, event_type_id: uuid.UUID) -> Publication | None:
        return await self.find_one(module_id=module_id, event_type_id=event_type_id)


class UserRepository(BaseRepository[User]):
    model = User

    def _loaded(self):
        return select(User).options(joinedload(User.module))

    async def get_by_email(self, email: str) -> User | None:
        stmt = self._loaded().where(User.email == email.strip().lower())
        return (await self.session.execute(stmt)).scalars().first()

    async def get_loaded(self, user_id: uuid.UUID) -> User | None:
        stmt = self._loaded().where(User.id == user_id)
        return (await self.session.execute(stmt)).scalars().first()

    async def list_for_module(self, module_id: uuid.UUID) -> list[User]:
        stmt = self._loaded().where(User.module_id == module_id).order_by(User.email)
        return list((await self.session.execute(stmt)).scalars().unique().all())

    async def list_all(self) -> list[User]:  # type: ignore[override]
        stmt = self._loaded().order_by(User.module_id, User.email)
        return list((await self.session.execute(stmt)).scalars().unique().all())

    async def count_active_in_module(self, module_id: uuid.UUID) -> int:
        """Se usa para no dejar a un equipo sin ninguna cuenta con la que entrar."""
        stmt = (
            select(func.count())
            .select_from(User)
            .where(User.module_id == module_id, User.active.is_(True))
        )
        return int((await self.session.execute(stmt)).scalar_one())

    async def count_active(self) -> int:
        stmt = select(func.count()).select_from(User).where(User.active.is_(True))
        return int((await self.session.execute(stmt)).scalar_one())

    async def record_failed_login(self, user: User, *, max_attempts: int) -> None:
        """Suma un intento fallido y **lo confirma en la base**.

        Tiene que commitear aca: el login termina levantando una excepcion, y la
        dependencia de sesion hace rollback ante cualquier error, asi que el
        contador se perderia y el bloqueo por intentos no serviria de nada.
        """
        user.failed_login_attempts += 1
        if user.failed_login_attempts >= max_attempts:
            user.active = False
        await self.session.commit()
